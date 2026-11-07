using UnityEngine;

public enum DemoMode
{
    Tutorial,
    GodMode,
    FullPlay
}

public class DemoModeManager : MonoBehaviour
{
    public static DemoModeManager Instance { get; private set; }

    [Header("Current Mode")]
    [SerializeField] private DemoMode currentMode = DemoMode.FullPlay;

    public DemoMode CurrentMode => currentMode;
    public bool IsGodMode => currentMode == DemoMode.GodMode || currentMode == DemoMode.Tutorial;
    public bool IsTutorial => currentMode == DemoMode.Tutorial;

    public delegate void DemoModeChangedHandler(DemoMode oldMode, DemoMode newMode);
    public event DemoModeChangedHandler OnDemoModeChanged;

    private void Awake()
    {
        if (Instance != null && Instance != this)
        {
            Destroy(gameObject);
            return;
        }
        Instance = this;
    }

    private void OnEnable()
    {
        GestureEvents.OnGestureReceived += HandleGesture;
    }

    private void OnDisable()
    {
        GestureEvents.OnGestureReceived -= HandleGesture;
    }

    private void HandleGesture(GestureAction action, float confidence)
    {
        switch (action)
        {
            case GestureAction.SET_TUTORIAL:
                SetMode(DemoMode.Tutorial);
                break;
            case GestureAction.SET_GOD_MODE:
                SetMode(DemoMode.GodMode);
                break;
            case GestureAction.SET_FULL_PLAY:
                SetMode(DemoMode.FullPlay);
                break;
        }
    }

    public void SetMode(DemoMode newMode)
    {
        if (currentMode == newMode) return;

        DemoMode oldMode = currentMode;
        currentMode = newMode;

        if (GameStateManager.Instance != null)
            GameStateManager.Instance.ResetToIdle();

        Debug.Log($"[DemoMode] {oldMode} -> {newMode}");
        OnDemoModeChanged?.Invoke(oldMode, newMode);
    }
}
