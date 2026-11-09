using System;
using System.Collections;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading;
using System.Threading.Tasks;
using CG4002.Comms;
using UnityEngine;
using UnityEngine.Networking;
using PairState = CG4002.Comms.PairingState;

public class NetworkManager : MonoBehaviour
{
    const string PhoneIdKey = "cg4002.phone_id";
    const string PairedDeviceKey = "cg4002.paired_device_id";
    const float RenewIntervalSeconds = 30f;
    const int PairingTimeoutMilliseconds = 8000;

    public static NetworkManager Instance { get; private set; }

    [Header("MQTT Gesture Settings")]
    [SerializeField, Range(0f, 1f)] private float minimumConfidence = 0f;

    [Header("Status")]
    [SerializeField] private string lastMessage = "";

    public SshMqttClient Client { get; private set; }
    public bool IsConnected => isActiveAndEnabled && !paused && Client?.IsConnected == true;
    public string Status => connectionError ?? (!isActiveAndEnabled ? "Disabled" :
        paused ? "Paused" : Client?.Status ?? "Loading settings...");
    public string LastAction { get; private set; }
    public string PhoneId => phoneId;
    public string PairedDeviceId => pairedDeviceId;
    public PairState PairingState => pairingState;
    public bool IsPaired => pairingState == PairState.Paired && !string.IsNullOrEmpty(pairedDeviceId);
    public bool MiddlePressPending { get; private set; }
    public bool IndexPressPending { get; private set; }
    public bool RingPressPending { get; private set; }
    public uint LastMenuControlSequence { get; private set; }

    public event Action DevicesChanged;
    public event Action PairingChanged;

    readonly Dictionary<string, PairableDevice> devices = new Dictionary<string, PairableDevice>();
    readonly Dictionary<string, TaskCompletionSource<PairingResult>> pendingPairing =
        new Dictionary<string, TaskCompletionSource<PairingResult>>();
    readonly object pendingGate = new object();
    readonly SemaphoreSlim pairingGate = new SemaphoreSlim(1, 1);

    string connectionError, phoneId, pairedDeviceId;
    PairState pairingState = PairState.Unpaired;
    bool paused, started, restartRequested = true, connectionWasUp;
    float nextRenewAt;
    CancellationTokenSource lifetime;
    Task networkTask, restoreTask, renewTask;

    private void Awake()
    {
        if (Instance != null && Instance != this)
        {
            Destroy(gameObject);
            return;
        }
        Instance = this;
        phoneId = PlayerPrefs.GetString(PhoneIdKey, "");
        if (!ValidIdentifier(phoneId))
        {
            phoneId = "phone-" + Guid.NewGuid().ToString("N").Substring(0, 24);
            PlayerPrefs.SetString(PhoneIdKey, phoneId);
            PlayerPrefs.Save();
        }
        pairedDeviceId = PlayerPrefs.GetString(PairedDeviceKey, "");
        if (!ValidPlayerId(pairedDeviceId)) pairedDeviceId = "";
    }

    private IEnumerator Start()
    {
        started = true;
        string path = Path.Combine(Application.streamingAssetsPath, "secrets.json");
        string url = path.Contains("://") ? path : new Uri(path).AbsoluteUri;
        using (var request = UnityWebRequest.Get(url))
        {
            yield return request.SendWebRequest();
            if (request.result != UnityWebRequest.Result.Success)
            {
                connectionError = "Cannot load secrets.json. Run root setup.sh before building.";
                yield break;
            }
            try
            {
                var settings = JsonUtility.FromJson<ConnectionSecrets>(request.downloadHandler.text);
                if (settings == null) throw new InvalidDataException("Empty connection settings.");
                Client = new SshMqttClient(settings, phoneId);
            }
            catch (Exception error) { connectionError = "Settings: " + error.Message; }
        }
    }

    private void OnEnable()
    {
        if (started) StartListening();
    }

    private void OnDisable()
    {
        StopListening();
    }

    private void Update()
    {
        ObserveTask(ref restoreTask, "Pairing restore");
        ObserveTask(ref renewTask, "Pairing renewal");
        if (networkTask != null && networkTask.IsCompleted)
        {
            if (networkTask.IsFaulted)
                connectionError = "Connection stopped: " + networkTask.Exception.GetBaseException().Message;
            networkTask = null;
            lifetime.Dispose();
            lifetime = null;
        }
        if (paused || !isActiveAndEnabled) return;
        if (restartRequested && Client != null && networkTask == null)
        {
            restartRequested = false;
            lifetime = new CancellationTokenSource();
            var token = lifetime.Token;
            networkTask = Task.Run(() => Client.RunAsync(token));
        }
        if (Client == null) return;

        for (int i = 0; i < 256 && Client.TryDequeue(out var message); i++)
            ProcessMqttMessage(message);

        bool connected = Client.IsConnected;
        if (connected && !connectionWasUp)
        {
            connectionWasUp = true;
            if (!string.IsNullOrEmpty(pairedDeviceId) && restoreTask == null)
                restoreTask = AcquirePairingAsync(pairedDeviceId, false, CancellationToken.None);
        }
        else if (!connected)
        {
            connectionWasUp = false;
            if (pairingState == PairState.Paired)
            {
                pairingState = PairState.Unpaired;
                PairingChanged?.Invoke();
            }
        }

        if (connected && IsPaired && renewTask == null && Time.realtimeSinceStartup >= nextRenewAt)
            renewTask = RenewPairingAsync();
    }

    public IReadOnlyList<PairableDevice> GetOnlineDevices() => devices.Values
        .Where(device => device.IsOnline).OrderBy(device => device.DeviceId).ToArray();

    public bool IsDeviceOnline(string deviceId) => ValidPlayerId(deviceId) &&
        devices.TryGetValue(deviceId, out var device) && device.IsOnline;

    public Task<PairingResult> PairAsync(string deviceId, CancellationToken cancellation = default) =>
        AcquirePairingAsync(deviceId, true, cancellation);

    public bool TryConsumeMenuControls(out bool middle, out bool index, out bool ring)
    {
        middle = MiddlePressPending;
        index = IndexPressPending;
        ring = RingPressPending;
        MiddlePressPending = IndexPressPending = RingPressPending = false;
        return middle || index || ring;
    }

    public void InjectMenuControl(bool index = false, bool middle = false, bool ring = false)
    {
        IndexPressPending |= index;
        MiddlePressPending |= middle;
        RingPressPending |= ring;
    }

    public async Task<PairingResult> ForgetPairingAsync(CancellationToken cancellation = default)
    {
        if (string.IsNullOrEmpty(pairedDeviceId))
            return LocalResult("RELEASED", "");
        await pairingGate.WaitAsync(cancellation);
        try
        {
            if (Client == null || !Client.IsConnected)
                return LocalResult("ERROR", pairedDeviceId, "Not connected.");
            var result = await SendPairingRequestAsync("release", pairedDeviceId, cancellation);
            if (result.Status == "RELEASED")
            {
                await Client.ClearPairedDeviceAsync(cancellation);
                ClearLocalPairing();
            }
            return result;
        }
        finally { pairingGate.Release(); }
    }

    async Task<PairingResult> AcquirePairingAsync(string deviceId, bool requireObservedOnline,
                                                   CancellationToken cancellation)
    {
        if (!ValidPlayerId(deviceId))
            return LocalResult("INVALID", deviceId, "Player ID must be 1 or 2.");
        if (requireObservedOnline && !IsDeviceOnline(deviceId))
            return LocalResult("OFFLINE", deviceId, "The ESP32 is not currently online.");
        await pairingGate.WaitAsync(cancellation);
        PairState previousState = pairingState;
        try
        {
            if (Client == null || !Client.IsConnected)
                return LocalResult("ERROR", deviceId, "Not connected.");
            pairingState = PairState.Acquiring;
            PairingChanged?.Invoke();
            var result = await SendPairingRequestAsync("acquire", deviceId, cancellation);
            if (result.Status == "ACQUIRED" || result.Status == "RECLAIMED")
            {
                pairedDeviceId = deviceId;
                PlayerPrefs.SetString(PairedDeviceKey, pairedDeviceId);
                PlayerPrefs.Save();
                await Client.SetPairedDeviceAsync(deviceId, cancellation);
                pairingState = PairState.Paired;
                nextRenewAt = Time.realtimeSinceStartup + RenewIntervalSeconds;
            }
            else pairingState = previousState == PairState.Paired
                ? PairState.Paired : PairState.Unpaired;
            PairingChanged?.Invoke();
            return result;
        }
        catch
        {
            if (pairedDeviceId == deviceId)
            {
                pairingState = PairState.Unpaired;
                connectionWasUp = false; // Retry lock restoration and the exact subscription.
            }
            else pairingState = previousState == PairState.Paired
                ? PairState.Paired : PairState.Unpaired;
            PairingChanged?.Invoke();
            throw;
        }
        finally { pairingGate.Release(); }
    }

    async Task RenewPairingAsync()
    {
        string deviceId = pairedDeviceId;
        if (!ValidPlayerId(deviceId)) return;
        await pairingGate.WaitAsync();
        bool reacquire = false;
        try
        {
            if (Client == null || !Client.IsConnected) return;
            var result = await SendPairingRequestAsync("renew", deviceId, CancellationToken.None);
            if (result.Status == "RENEWED")
                nextRenewAt = Time.realtimeSinceStartup + RenewIntervalSeconds;
            else if (result.Status == "EXPIRED")
            {
                await Client.ClearPairedDeviceAsync();
                pairingState = PairState.Unpaired;
                PairingChanged?.Invoke();
                reacquire = true;
            }
            else if (result.Status == "LOCKED")
            {
                await Client.ClearPairedDeviceAsync();
                ClearLocalPairing();
            }
        }
        finally { pairingGate.Release(); }
        if (reacquire)
            await AcquirePairingAsync(deviceId, false, CancellationToken.None);
    }

    async Task<PairingResult> SendPairingRequestAsync(string action, string deviceId,
                                                       CancellationToken cancellation)
    {
        string requestId = Guid.NewGuid().ToString("N");
        var completion = new TaskCompletionSource<PairingResult>(TaskCreationOptions.RunContinuationsAsynchronously);
        lock (pendingGate) pendingPairing.Add(requestId, completion);
        try
        {
            string json = JsonUtility.ToJson(new PairingRequest {
                action = action, request_id = requestId, device_id = deviceId
            });
            await Client.PublishPairingRequestAsync(json, cancellation);
            Task timeout = Task.Delay(PairingTimeoutMilliseconds, cancellation);
            Task finished = await Task.WhenAny(completion.Task, timeout);
            if (finished != completion.Task)
            {
                cancellation.ThrowIfCancellationRequested();
                throw new TimeoutException("Pairing request timed out.");
            }
            return await completion.Task;
        }
        finally
        {
            lock (pendingGate) pendingPairing.Remove(requestId);
        }
    }

    void ProcessMqttMessage(ReceivedMessage message)
    {
        if (message == null) return;
        if (message.Topic == $"visualiser/{phoneId}/pair/result")
        {
            ProcessPairingResult(message.Text);
            return;
        }
        if (!string.IsNullOrEmpty(message.ModelId) &&
            message.Topic == $"ultra96/{message.ModelId}/status")
        {
            ProcessDeviceStatus(message);
            return;
        }
        if (!IsPaired || message.ModelId != pairedDeviceId) return;
        if (message.Topic == $"ultra96/{pairedDeviceId}/menu_controls")
        {
            ProcessMenuControls(message.Text);
            return;
        }
        if (message.Topic != $"ultra96/{pairedDeviceId}/inference") return;
        lastMessage = message.Text;
        ProcessGesture(message.Text);
    }

    void ProcessDeviceStatus(ReceivedMessage message)
    {
        DeviceStatusPayload payload;
        try { payload = JsonUtility.FromJson<DeviceStatusPayload>(message.Text); }
        catch (ArgumentException) { return; }
        bool online = payload != null && payload.state == "online";
        devices[message.ModelId] = new PairableDevice(
            message.ModelId, online, message.Text, message.ReceivedAtUtc);
        DevicesChanged?.Invoke();
        if (online && pairingState == PairState.Unpaired &&
            pairedDeviceId == message.ModelId && Client.IsConnected && restoreTask == null)
            restoreTask = AcquirePairingAsync(pairedDeviceId, false, CancellationToken.None);
    }

    void ProcessPairingResult(string json)
    {
        PairingWireResult wire;
        try { wire = JsonUtility.FromJson<PairingWireResult>(json); }
        catch (ArgumentException) { return; }
        if (wire == null || !ValidIdentifier(wire.request_id)) return;
        TaskCompletionSource<PairingResult> completion;
        lock (pendingGate) pendingPairing.TryGetValue(wire.request_id, out completion);
        completion?.TrySetResult(new PairingResult(wire));
    }

    void ProcessGesture(string jsonMessage)
    {
        try
        {
            GesturePayload payload = JsonUtility.FromJson<GesturePayload>(jsonMessage);
            if (payload == null || float.IsNaN(payload.confidence) ||
                float.IsInfinity(payload.confidence) || payload.confidence < 0f ||
                payload.confidence > 1f || payload.timestamp < 0)
                throw new FormatException("Invalid gesture payload.");
            GestureAction action = payload.GetGestureAction();
            if (action == GestureAction.NONE)
            {
                Debug.LogWarning($"[Network] Unknown gesture: {jsonMessage}");
                return;
            }
            if (payload.confidence < minimumConfidence) return;
            LastAction = action.ToString();
            Debug.Log($"[Network] Gesture received: {action} (confidence: {payload.confidence:F2})");
            if (action == GestureAction.ARM_PULLBACK)
                GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_CATCH, payload.confidence);
            GestureEvents.RaiseGestureReceived(action, payload.confidence);
        }
        catch (Exception error)
        {
            Debug.LogError($"[Network] Failed to parse message: {error.Message}\nRaw: {jsonMessage}");
        }
    }

    void ProcessMenuControls(string jsonMessage)
    {
        try
        {
            MenuControlsPayload payload = JsonUtility.FromJson<MenuControlsPayload>(jsonMessage);
            if (payload == null || payload.sequence < 0 || payload.sequence > uint.MaxValue ||
                payload.flags < 1 || payload.flags > 7)
                throw new FormatException("Invalid menu-control payload.");
            // Ultra96 also uses this index pulse to toggle CATCH_THROW/BATTLE_THROW;
            // it remains forwarded so Unity can still treat index as menu select.
            IndexPressPending |= (payload.flags & 0x01) != 0;
            MiddlePressPending |= (payload.flags & 0x02) != 0;
            RingPressPending |= (payload.flags & 0x04) != 0;
            LastMenuControlSequence = (uint)payload.sequence;
        }
        catch (Exception error)
        {
            Debug.LogWarning($"[Network] Ignoring menu-control message: {error.Message}");
        }
    }

    void ClearLocalPairing()
    {
        pairedDeviceId = "";
        pairingState = PairState.Unpaired;
        PlayerPrefs.DeleteKey(PairedDeviceKey);
        PlayerPrefs.Save();
        PairingChanged?.Invoke();
    }

    static PairingResult LocalResult(string status, string deviceId, string detail = null) =>
        new PairingResult(new PairingWireResult {
            request_id = "local", status = status, device_id = deviceId,
            lease_remaining_ms = 0, detail = detail
        });

    static bool ValidIdentifier(string value) => !string.IsNullOrEmpty(value) && value.Length <= 64 &&
        value.All(c => (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
            (c >= '0' && c <= '9') || c == '-' || c == '_');

    static bool ValidPlayerId(string value) => value == "1" || value == "2";

    static void ObserveTask(ref Task task, string operation)
    {
        if (task == null || !task.IsCompleted) return;
        if (task.IsFaulted) Debug.LogWarning($"[Network] {operation} failed: {task.Exception.GetBaseException().Message}");
        task = null;
    }

    public void Reconnect()
    {
        if (Client == null) return;
        connectionError = null;
        restartRequested = true;
        lifetime?.Cancel();
    }

    private void OnApplicationPause(bool value)
    {
        paused = value;
        if (value) StopListening();
        else if (started && isActiveAndEnabled) StartListening();
    }

    public void StartListening()
    {
        restartRequested = true;
    }

    private void OnDestroy()
    {
        StopListening();
        if (Instance == this) Instance = null;
        lock (pendingGate)
            foreach (var pending in pendingPairing.Values)
                pending.TrySetException(new ObjectDisposedException(nameof(NetworkManager)));
        var source = lifetime;
        if (networkTask != null)
            _ = networkTask.ContinueWith(task => {
                _ = task.Exception;
                source?.Dispose();
            }, TaskScheduler.Default);
        else source?.Dispose();
        networkTask = null;
        lifetime = null;
    }

    private void OnApplicationQuit()
    {
        StopListening();
    }

    private void StopListening()
    {
        restartRequested = false;
        lifetime?.Cancel();
    }
}
