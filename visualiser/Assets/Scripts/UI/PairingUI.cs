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
    [SerializeField] private TextMeshProUGUI device1Label;
    [SerializeField] private TextMeshProUGUI device1Status;
    [SerializeField] private Image device1Highlight;

    [Header("Device 2")]
    [SerializeField] private TextMeshProUGUI device2Label;
    [SerializeField] private TextMeshProUGUI device2Status;
    [SerializeField] private Image device2Highlight;

    [Header("Buttons")]
    [SerializeField] private Button unpairButton;

    [Header("Feedback")]
    [SerializeField] private TextMeshProUGUI statusMessageText;

    [Header("Colors")]
    [SerializeField] private Color onlineColor = Color.green;
    [SerializeField] private Color offlineColor = Color.gray;
    [SerializeField] private Color selectedColor = new Color(1f, 1f, 1f, 0.3f);
    [SerializeField] private Color unselectedColor = new Color(0f, 0f, 0f, 0f);

    private int selectedIndex;
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

        if (isPairing) return;

        var net = NetworkManager.Instance;
        if (net == null) return;

        if (net.TryConsumeMenuControls(out bool middle, out bool index, out bool ring))
        {
            int count = SelectableCount();

            if (middle)
            {
                selectedIndex = (selectedIndex - 1 + count) % count;
                UpdateSelectionHighlight();
            }
            if (ring)
            {
                selectedIndex = (selectedIndex + 1) % count;
                UpdateSelectionHighlight();
            }
            if (index)
                ExecuteSelection();
        }
    }

    public void Show()
    {
        if (pairingPanel != null)
            pairingPanel.SetActive(true);

        selectedIndex = 0;
        isPairing = false;
        RefreshDeviceList();
        RefreshConnectionStatus();
        UpdateSelectionHighlight();
        UpdateUnpairButton();
        SetStatusMessage("");
    }

    public void Hide()
    {
        if (pairingPanel != null)
            pairingPanel.SetActive(false);
    }

    public bool IsVisible => pairingPanel != null && pairingPanel.activeSelf;

    private int SelectableCount()
    {
        var net = NetworkManager.Instance;
        bool showUnpair = net != null && net.IsPaired;
        return showUnpair ? 3 : 2;
    }

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

    private void UpdateSelectionHighlight()
    {
        if (device1Highlight != null)
            device1Highlight.color = selectedIndex == 0 ? selectedColor : unselectedColor;
        if (device2Highlight != null)
            device2Highlight.color = selectedIndex == 1 ? selectedColor : unselectedColor;

        if (unpairButton != null)
        {
            var colors = unpairButton.colors;
            colors.normalColor = selectedIndex == 2 ? selectedColor : unselectedColor;
            unpairButton.colors = colors;
        }
    }

    private void UpdateUnpairButton()
    {
        var net = NetworkManager.Instance;
        bool showUnpair = net != null && net.IsPaired;
        if (unpairButton != null)
            unpairButton.gameObject.SetActive(showUnpair);

        if (selectedIndex >= SelectableCount())
            selectedIndex = 0;
        UpdateSelectionHighlight();
    }

    private void ExecuteSelection()
    {
        switch (selectedIndex)
        {
            case 0: PairWithDevice("1"); break;
            case 1: PairWithDevice("2"); break;
            case 2: ForgetPairing(); break;
        }
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
