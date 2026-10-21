using System;
using System.Collections;
using System.IO;
using System.Threading;
using System.Threading.Tasks;
using CG4002.Comms;
using UnityEngine;
using UnityEngine.Networking;

public class NetworkManager : MonoBehaviour
{
    public static NetworkManager Instance { get; private set; }

    [Header("MQTT Gesture Settings")]
    [Tooltip("FireBeetle model ID. Empty accepts all devices for a single-device demo.")]
    [SerializeField] private string modelId = "";
    [SerializeField, Range(0f, 1f)] private float minimumConfidence = 0f;

    [Header("Status")]
    [SerializeField] private string lastMessage = "";

    public SshMqttClient Client { get; private set; }
    public bool IsConnected => isActiveAndEnabled && !paused && Client?.IsConnected == true;
    public string Status => connectionError ?? (!isActiveAndEnabled ? "Disabled" :
        paused ? "Paused" : Client?.Status ?? "Loading settings...");
    public string LastAction { get; private set; }

    private string connectionError;
    private bool paused, started, restartRequested = true;
    private CancellationTokenSource lifetime;
    private Task networkTask;

    private void Awake()
    {
        if (Instance != null && Instance != this)
        {
            Destroy(gameObject);
            return;
        }
        Instance = this;
    }

    private IEnumerator Start()
    {
        started = true;
        string path = Path.Combine(Application.streamingAssetsPath, "secrets.json");
        string url = path.Contains("://") ? path : new Uri(path).AbsoluteUri;
        // StreamingAssets is inside the APK on Android, so read it via UnityWebRequest.
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
                Client = new SshMqttClient(settings);
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
        if (networkTask != null && networkTask.IsCompleted)
        {
            if (networkTask.IsFaulted)
                connectionError = "Connection stopped: " + networkTask.Exception.GetBaseException().Message;
            networkTask = null;
            lifetime.Dispose();
            lifetime = null;
        }
        if (paused || !isActiveAndEnabled) return;
        // Wait for the previous SSH tunnels to close before reconnecting.
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
    }

    private void ProcessMqttMessage(ReceivedMessage message)
    {
        // The client also receives binary telemetry and status on other topics.
        if (message == null || string.IsNullOrEmpty(message.ModelId) ||
            message.Topic != $"ultra96/{message.ModelId}/inference" ||
            (!string.IsNullOrEmpty(modelId) && message.ModelId != modelId))
            return;
        lastMessage = message.Text;
        ProcessMessage(message.Text);
    }

    public void Reconnect()
    {
        if (Client == null) return; // Fix invalid settings and restart the scene.
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

    private void ProcessMessage(string jsonMessage)
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
            // The existing battle handler needs catch mode before Aim. Outside
            // battle this preparation event is ignored by the gameplay handlers.
            if (action == GestureAction.ARM_PULLBACK)
                GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_CATCH, payload.confidence);
            GestureEvents.RaiseGestureReceived(action, payload.confidence);
        }
        catch (Exception e)
        {
            Debug.LogError($"[Network] Failed to parse message: {e.Message}\nRaw: {jsonMessage}");
        }
    }

    private void OnDestroy()
    {
        StopListening();
        if (Instance == this) Instance = null;
        var source = lifetime;
        if (networkTask != null)
            _ = networkTask.ContinueWith(task => {
                // Observe faults and release resources without Unity calls from the worker.
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