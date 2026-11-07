using System;
using UnityEngine;
using UnityEngine.UI;
using TMPro;
using CG4002.Comms;

public class PairingUI : MonoBehaviour
{
    public static PairingUI Instance { get; private set; }

    [Header("Panel")]
    [SerializeField] private GameObject pairingPanel;

    [Header("Connection Status")]
    [SerializeField] private TextMeshProUGUI connectionStatusText;

    [Header("Device 1")]
    [SerializeField] private Button device1Button;
    [SerializeField] private TextMeshProUGUI device1Status;

    [Header("Device 2")]
    [SerializeField] private Button device2Button;
    [SerializeField] private TextMeshProUGUI device2Status;

    [Header("Buttons")]
    [SerializeField] private Button unpairButton;

    [Header("Feedback")]
    [SerializeField] private TextMeshProUGUI statusMessageText;

    [Header("Colors")]
    [SerializeField] private Color onlineColor = Color.green;
    [SerializeField] private Color offlineColor = Color.gray;

    private bool isPairing;

    private void Awake()
    {
        if (Instance != null && Instance != this)
        {
            Destroy(gameObject);
            return;
        }
        Instance = this;
    }

    private void Start()
    {
        if (device1Button != null)
            device1Button.onClick.AddListener(() => PairWithDevice("1"));
        if (device2Button != null)
            device2Button.onClick.AddListener(() => PairWithDevice("2"));
        if (unpairButton != null)
            unpairButton.onClick.AddListener(ForgetPairing);

        var net = NetworkManager.Instance;
        if (net != null && net.IsPaired)
        {
            Hide();
            ModeSelectUI.Instance?.Show();
            return;
        }

        Show();
    }

    private void OnEnable()
    {
        var net = NetworkManager.Instance;
        if (net == null) return;
        net.DevicesChanged += RefreshDeviceList;
        net.PairingChanged += RefreshPairingState;
    }

    private void OnDisable()
    {
        var net = NetworkManager.Instance;
        if (net == null) return;
        net.DevicesChanged -= RefreshDeviceList;
        net.PairingChanged -= RefreshPairingState;
    }

    private void Update()
    {
        if (!pairingPanel.activeSelf) return;
        RefreshConnectionStatus();
    }

    public void Show()
    {
        if (pairingPanel != null)
            pairingPanel.SetActive(true);

        isPairing = false;
        RefreshDeviceList();
        RefreshConnectionStatus();
        UpdateUnpairButton();
        SetStatusMessage("");
    }

    public void Hide()
    {
        if (pairingPanel != null)
            pairingPanel.SetActive(false);
    }

    public bool IsVisible => pairingPanel != null && pairingPanel.activeSelf;

    private void RefreshDeviceList()
    {
        var net = NetworkManager.Instance;
        if (net == null) return;

        bool d1Online = net.IsDeviceOnline("1");
        bool d2Online = net.IsDeviceOnline("2");

        if (device1Status != null)
        {
            device1Status.text = d1Online ? "Online" : "Offline";
            device1Status.color = d1Online ? onlineColor : offlineColor;
        }
        if (device2Status != null)
        {
            device2Status.text = d2Online ? "Online" : "Offline";
            device2Status.color = d2Online ? onlineColor : offlineColor;
        }

        if (device1Button != null)
            device1Button.interactable = d1Online && !isPairing;
        if (device2Button != null)
            device2Button.interactable = d2Online && !isPairing;
    }

    private void RefreshPairingState()
    {
        var net = NetworkManager.Instance;
        if (net == null) return;

        UpdateUnpairButton();

        if (net.IsPaired && pairingPanel.activeSelf)
        {
            SetStatusMessage($"Paired to Player {net.PairedDeviceId}");
            Hide();
            ModeSelectUI.Instance?.Show();
        }
    }

    private void RefreshConnectionStatus()
    {
        if (connectionStatusText == null) return;
        var net = NetworkManager.Instance;
        if (net == null)
        {
            connectionStatusText.text = "Disconnected";
            return;
        }
        connectionStatusText.text = net.IsConnected ? "Connected" : "Disconnected";
    }

    private void UpdateUnpairButton()
    {
        var net = NetworkManager.Instance;
        bool showUnpair = net != null && net.IsPaired;
        if (unpairButton != null)
            unpairButton.gameObject.SetActive(showUnpair);
    }

    private async void PairWithDevice(string deviceId)
    {
        var net = NetworkManager.Instance;
        if (net == null) return;

        if (!net.IsDeviceOnline(deviceId))
        {
            SetStatusMessage($"Player {deviceId} is offline");
            return;
        }

        isPairing = true;
        SetStatusMessage("Pairing...");
        RefreshDeviceList();

        try
        {
            PairingResult result = await net.PairAsync(deviceId);

            if (result.Succeeded)
            {
                SetStatusMessage($"Paired to Player {deviceId}");
                Hide();
                ModeSelectUI.Instance?.Show();
            }
            else
            {
                SetStatusMessage($"Failed: {result.Status}");
            }
        }
        catch (Exception ex)
        {
            Debug.LogError($"[PairingUI] PairAsync error: {ex}");
            SetStatusMessage("Pairing error");
        }
        finally
        {
            isPairing = false;
            RefreshDeviceList();
        }
    }

    private async void ForgetPairing()
    {
        var net = NetworkManager.Instance;
        if (net == null || !net.IsPaired) return;

        isPairing = true;
        SetStatusMessage("Releasing...");

        try
        {
            PairingResult result = await net.ForgetPairingAsync();

            if (result.Succeeded)
                SetStatusMessage("Unpaired");
            else
                SetStatusMessage($"Failed: {result.Status}");
        }
        catch (Exception ex)
        {
            Debug.LogError($"[PairingUI] ForgetPairingAsync error: {ex}");
            SetStatusMessage("Unpair error");
        }
        finally
        {
            isPairing = false;
            UpdateUnpairButton();
            RefreshDeviceList();
        }
    }

    private void SetStatusMessage(string message)
    {
        if (statusMessageText != null)
            statusMessageText.text = message;
    }
}
