using UnityEngine;

public enum GamePhase
{
    Idle,           // No encounter, scanning environment
    Encounter,      // Wild Pokemon appeared, waiting for user action
    CatchAttempt,   // User chose to catch, pokeball in flight
    BattleEntry,    // User chose to battle, sending out own Pokemon
    BattleActive,   // Battle in progress, waiting for move gestures
    BattleResult,   // Battle ended (win/lose)
    CatchResult     // Catch succeeded or failed
}

public class GameStateManager : MonoBehaviour
{
    public static GameStateManager Instance { get; private set; }

    [Header("Current State")]
    [SerializeField] private GamePhase currentPhase = GamePhase.Idle;

    public GamePhase CurrentPhase => currentPhase;

    public delegate void PhaseChangedHandler(GamePhase oldPhase, GamePhase newPhase);
    public event PhaseChangedHandler OnPhaseChanged;

    private void Awake()
    {
        if (Instance != null && Instance != this)
        {
            Destroy(gameObject);
            return;
        }
        Instance = this;
        DontDestroyOnLoad(gameObject);
    }

    public void TransitionTo(GamePhase newPhase)
    {
        if (currentPhase == newPhase) return;

        if (!IsValidTransition(currentPhase, newPhase))
        {
            Debug.LogWarning($"Invalid state transition: {currentPhase} -> {newPhase}");
            return;
        }

        GamePhase oldPhase = currentPhase;
        currentPhase = newPhase;

        Debug.Log($"[GameState] {oldPhase} -> {newPhase}");
        OnPhaseChanged?.Invoke(oldPhase, newPhase);
    }

    private bool IsValidTransition(GamePhase from, GamePhase to)
    {
        return (from, to) switch
        {
            (GamePhase.Idle, GamePhase.Encounter) => true,
            (GamePhase.Encounter, GamePhase.CatchAttempt) => true,
            (GamePhase.Encounter, GamePhase.BattleEntry) => true,
            (GamePhase.CatchAttempt, GamePhase.CatchResult) => true,
            (GamePhase.CatchResult, GamePhase.Idle) => true,
            (GamePhase.CatchResult, GamePhase.Encounter) => true,  // catch failed, pokemon still there
            (GamePhase.BattleEntry, GamePhase.BattleActive) => true,
            (GamePhase.BattleActive, GamePhase.BattleResult) => true,
            (GamePhase.BattleResult, GamePhase.Idle) => true,
            // Allow reset to Idle from any state (for debug/error recovery)
            (_, GamePhase.Idle) => true,
            _ => false
        };
    }

    public void ResetToIdle()
    {
        GamePhase oldPhase = currentPhase;
        currentPhase = GamePhase.Idle;
        OnPhaseChanged?.Invoke(oldPhase, GamePhase.Idle);
    }
}
