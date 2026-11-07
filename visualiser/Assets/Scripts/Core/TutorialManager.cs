using System;
using System.Collections;
using System.Threading;
using UnityEngine;

public class TutorialManager : MonoBehaviour
{
    public static TutorialManager Instance { get; private set; }

    [Serializable]
    public class TutorialStep
    {
        public string name;
        public string instruction;
        public GestureAction expectedGesture;
        public bool autoAdvanceOnPhase;
        public GamePhase triggerPhase;
        public float autoAdvanceDelay;
        public bool forceSpawnBefore;
        public bool forceSpawnAfter;
    }

    private readonly TutorialStep[] steps = new TutorialStep[]
    {
        new TutorialStep {
            name = "Scan Environment",
            instruction = "Pan your camera slowly to scan the room",
            expectedGesture = GestureAction.NONE,
            autoAdvanceDelay = 8f
        },
        new TutorialStep {
            name = "Encounter",
            instruction = "A wild Pokemon will appear!",
            expectedGesture = GestureAction.NONE,
            autoAdvanceOnPhase = true,
            triggerPhase = GamePhase.Encounter,
            forceSpawnBefore = true,
            autoAdvanceDelay = 5f
        },
        new TutorialStep {
            name = "Aim",
            instruction = "Pull your arm back to aim at the Pokemon",
            expectedGesture = GestureAction.ARM_PULLBACK
        },
        new TutorialStep {
            name = "Catch Throw",
            instruction = "Throw to catch the Pokemon!",
            expectedGesture = GestureAction.CATCH_THROW,
            forceSpawnAfter = true
        },
        new TutorialStep {
            name = "Battle Entry",
            instruction = "A new Pokemon appeared! Press the button on your index finger to toggle to your own Pokemon, then aim and throw your Pokemon to battle!",
            expectedGesture = GestureAction.POKEBALL_THROW,
            forceSpawnBefore = true,
            autoAdvanceOnPhase = true,
            triggerPhase = GamePhase.BattleActive
        },
        new TutorialStep {
            name = "Attack",
            instruction = "Use Move 1 (Close Combat) to attack!",
            expectedGesture = GestureAction.BATTLE_MOVE_1
        },
        new TutorialStep {
            name = "Protect",
            instruction = "Use Move 2 (Protect) to block the next attack!",
            expectedGesture = GestureAction.BATTLE_MOVE_2
        },
        new TutorialStep {
            name = "Battle Catch",
            instruction = "Aim and throw to catch the Pokemon in battle!",
            expectedGesture = GestureAction.BATTLE_CATCH
        },
        new TutorialStep {
            name = "Run Away",
            instruction = "Turn around to run from battle!",
            expectedGesture = GestureAction.BATTLE_RUN
        },
        new TutorialStep {
            name = "Complete",
            instruction = "Tutorial complete! You're ready to play!",
            expectedGesture = GestureAction.NONE,
            autoAdvanceDelay = 5f
        }
    };

    private int currentStepIndex = -1;
    private bool isActive;
    private Coroutine autoAdvanceCoroutine;

    public int CurrentStepIndex => currentStepIndex;
    public int TotalSteps => steps.Length;
    public TutorialStep CurrentStep => (currentStepIndex >= 0 && currentStepIndex < steps.Length)
        ? steps[currentStepIndex] : null;
    public bool IsActive => isActive;

    public delegate void StepChangedHandler(int stepIndex, TutorialStep step);
    public event StepChangedHandler OnStepChanged;

    public delegate void TutorialEventHandler(string message);
    public event TutorialEventHandler OnTutorialFeedback;

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
        if (DemoModeManager.Instance != null)
            DemoModeManager.Instance.OnDemoModeChanged += HandleModeChanged;
        GestureEvents.OnGestureReceived += HandleGesture;
        if (GameStateManager.Instance != null)
            GameStateManager.Instance.OnPhaseChanged += HandlePhaseChanged;
    }

    private void Start()
    {
        if (DemoModeManager.Instance != null)
        {
            DemoModeManager.Instance.OnDemoModeChanged -= HandleModeChanged;
            DemoModeManager.Instance.OnDemoModeChanged += HandleModeChanged;
        }
        if (GameStateManager.Instance != null)
        {
            GameStateManager.Instance.OnPhaseChanged -= HandlePhaseChanged;
            GameStateManager.Instance.OnPhaseChanged += HandlePhaseChanged;
        }
    }

    private void OnDisable()
    {
        if (DemoModeManager.Instance != null)
            DemoModeManager.Instance.OnDemoModeChanged -= HandleModeChanged;
        GestureEvents.OnGestureReceived -= HandleGesture;
        if (GameStateManager.Instance != null)
            GameStateManager.Instance.OnPhaseChanged -= HandlePhaseChanged;
    }

    private void HandleModeChanged(DemoMode oldMode, DemoMode newMode)
    {
        if (newMode == DemoMode.Tutorial)
            StartTutorial();
        else
            StopTutorial();
    }

    public void StartTutorial()
    {
        isActive = true;
        currentStepIndex = -1;
        AdvanceStep();
    }

    public void StopTutorial()
    {
        isActive = false;
        if (autoAdvanceCoroutine != null)
        {
            StopCoroutine(autoAdvanceCoroutine);
            autoAdvanceCoroutine = null;
        }
        currentStepIndex = -1;
    }

    public void AdvanceStep()
    {
        if (!isActive) return;

        if (autoAdvanceCoroutine != null)
        {
            StopCoroutine(autoAdvanceCoroutine);
            autoAdvanceCoroutine = null;
        }

        currentStepIndex++;

        if (currentStepIndex >= steps.Length)
        {
            CompleteTutorial();
            return;
        }

        TutorialStep step = steps[currentStepIndex];
        Debug.Log($"[Tutorial] Step {currentStepIndex + 1}/{steps.Length}: {step.name}");

        if (step.forceSpawnBefore)
        {
            StartCoroutine(ForceSpawnForStep());
        }

        OnStepChanged?.Invoke(currentStepIndex, step);
        PublishStepToMqtt();

        if (step.autoAdvanceDelay > 0 && step.expectedGesture == GestureAction.NONE)
        {
            autoAdvanceCoroutine = StartCoroutine(AutoAdvanceAfterDelay(step.autoAdvanceDelay));
        }
    }

    public void SkipStep()
    {
        if (!isActive) return;
        AdvanceStep();
    }

    private void HandleGesture(GestureAction action, float confidence)
    {
        if (!isActive || currentStepIndex < 0 || currentStepIndex >= steps.Length) return;

        if (action == GestureAction.SKIP_STEP)
        {
            SkipStep();
            return;
        }

        TutorialStep step = steps[currentStepIndex];
        if (step.expectedGesture == GestureAction.NONE) return;

        if (action == step.expectedGesture)
        {
            OnTutorialFeedback?.Invoke("Great job!");
            StartCoroutine(DelayedAdvance(1.5f));
        }
    }

    private void HandlePhaseChanged(GamePhase oldPhase, GamePhase newPhase)
    {
        if (!isActive || currentStepIndex < 0 || currentStepIndex >= steps.Length) return;

        TutorialStep step = steps[currentStepIndex];
        if (step.autoAdvanceOnPhase && newPhase == step.triggerPhase)
        {
            OnTutorialFeedback?.Invoke("Great job!");
            StartCoroutine(DelayedAdvance(2f));
        }
    }

    private IEnumerator DelayedAdvance(float delay)
    {
        yield return new WaitForSeconds(delay);

        TutorialStep step = (currentStepIndex >= 0 && currentStepIndex < steps.Length)
            ? steps[currentStepIndex] : null;
        if (step != null && step.forceSpawnAfter)
        {
            if (GameStateManager.Instance != null)
                GameStateManager.Instance.ResetToIdle();
            yield return new WaitForSeconds(1f);
        }

        AdvanceStep();
    }

    private IEnumerator AutoAdvanceAfterDelay(float delay)
    {
        yield return new WaitForSeconds(delay);
        AdvanceStep();
    }

    private IEnumerator ForceSpawnForStep()
    {
        yield return new WaitForSeconds(1.5f);

        if (GameStateManager.Instance != null &&
            GameStateManager.Instance.CurrentPhase == GamePhase.Idle)
        {
            PokemonSpawner spawner = FindFirstObjectByType<PokemonSpawner>();
            if (spawner != null)
                spawner.ForceSpawn();
        }
    }

    private void CompleteTutorial()
    {
        isActive = false;
        Debug.Log("[Tutorial] Tutorial complete!");
        OnTutorialFeedback?.Invoke("Tutorial complete! Switching to Full Play mode.");

        StartCoroutine(SwitchToFullPlayAfterDelay(3f));
    }

    private IEnumerator SwitchToFullPlayAfterDelay(float delay)
    {
        yield return new WaitForSeconds(delay);
        if (DemoModeManager.Instance != null)
            DemoModeManager.Instance.SetMode(DemoMode.FullPlay);
    }

    private void PublishStepToMqtt()
    {
        if (NetworkManager.Instance == null || NetworkManager.Instance.Client == null) return;
        if (!NetworkManager.Instance.IsConnected) return;

        TutorialStep step = steps[currentStepIndex];
        string json = $"{{\"step\":{currentStepIndex + 1},\"total\":{steps.Length}," +
                       $"\"name\":\"{step.name}\",\"instruction\":\"{step.instruction}\"}}";

        _ = NetworkManager.Instance.Client.PublishAsync(
            "tutorial/step", json, CancellationToken.None);
    }
}
