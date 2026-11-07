using UnityEngine;
using UnityEngine.UI;
using TMPro;

public class ModeSelectUI : MonoBehaviour
{
    public static ModeSelectUI Instance { get; private set; }

    [Header("Panel")]
    [SerializeField] private GameObject modeSelectPanel;

    [Header("Buttons")]
    [SerializeField] private Button tutorialButton;
    [SerializeField] private Button godModeButton;
    [SerializeField] private Button fullPlayButton;
    [SerializeField] private Button pairDeviceButton;

    [Header("Settings")]
    [SerializeField] private bool showOnStart = true;

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
        if (tutorialButton != null)
            tutorialButton.onClick.AddListener(() => SelectMode(DemoMode.Tutorial));
        if (godModeButton != null)
            godModeButton.onClick.AddListener(() => SelectMode(DemoMode.GodMode));
        if (fullPlayButton != null)
            fullPlayButton.onClick.AddListener(() => SelectMode(DemoMode.FullPlay));
        if (pairDeviceButton != null)
            pairDeviceButton.onClick.AddListener(OpenPairing);

        if (showOnStart)
            Show();
        else
            Hide();
    }

    private void SelectMode(DemoMode mode)
    {
        if (DemoModeManager.Instance != null)
            DemoModeManager.Instance.SetMode(mode);
        Hide();
    }

    public void Show()
    {
        if (modeSelectPanel != null)
            modeSelectPanel.SetActive(true);
    }

    public void Hide()
    {
        if (modeSelectPanel != null)
            modeSelectPanel.SetActive(false);
    }

    private void OpenPairing()
    {
        Hide();
        PairingUI.Instance?.Show();
    }

    public bool IsVisible => modeSelectPanel != null && modeSelectPanel.activeSelf;
}
