using UnityEngine;

/// <summary>
/// Debug controller that simulates gesture inputs via keyboard.
/// Attach to any GameObject in the scene during development.
/// Disable or remove before final build.
/// </summary>
public class MockInputController : MonoBehaviour
{
    [Header("Enable/Disable")]
    [SerializeField] private bool enableMockInput = true;

    [Header("Key Bindings")]
    [SerializeField] private KeyCode aimKey = KeyCode.A;
    [SerializeField] private KeyCode catchThrowKey = KeyCode.C;
    [SerializeField] private KeyCode cancelKey = KeyCode.X;
    [SerializeField] private KeyCode battleEntryKey = KeyCode.B;
    [SerializeField] private KeyCode move1Key = KeyCode.Alpha1;
    [SerializeField] private KeyCode move2Key = KeyCode.Alpha2;
    [SerializeField] private KeyCode move3Key = KeyCode.Alpha3;
    [SerializeField] private KeyCode move4Key = KeyCode.Alpha4;
    [SerializeField] private KeyCode resetKey = KeyCode.R;

    [Header("Mock Confidence")]
    [SerializeField] private float mockConfidence = 0.95f;

    private void Update()
    {
        if (!enableMockInput) return;

        if (Input.GetKeyDown(aimKey))
        {
            Debug.Log("[MockInput] ARM_PULLBACK triggered (show reticle)");
            GestureEvents.RaiseGestureReceived(GestureAction.ARM_PULLBACK, mockConfidence);
        }

        if (Input.GetKeyDown(catchThrowKey))
        {
            Debug.Log("[MockInput] CATCH_THROW triggered");
            GestureEvents.RaiseGestureReceived(GestureAction.CATCH_THROW, mockConfidence);
        }

        if (Input.GetKeyDown(cancelKey))
        {
            Debug.Log("[MockInput] CANCEL triggered (hide reticle)");
            GestureEvents.RaiseGestureReceived(GestureAction.CANCEL, mockConfidence);
        }

        if (Input.GetKeyDown(battleEntryKey))
        {
            Debug.Log("[MockInput] POKEBALL_THROW triggered (battle entry)");
            GestureEvents.RaiseGestureReceived(GestureAction.POKEBALL_THROW, mockConfidence);
        }

        if (Input.GetKeyDown(move1Key))
        {
            Debug.Log("[MockInput] BATTLE_MOVE_1: Close Combat");
            GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_MOVE_1, mockConfidence);
        }

        if (Input.GetKeyDown(move2Key))
        {
            Debug.Log("[MockInput] BATTLE_MOVE_2: Protect");
            GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_MOVE_2, mockConfidence);
        }

        if (Input.GetKeyDown(move3Key))
        {
            Debug.Log("[MockInput] BATTLE_MOVE_3: Brick Break");
            GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_MOVE_3, mockConfidence);
        }

        if (Input.GetKeyDown(move4Key))
        {
            Debug.Log("[MockInput] BATTLE_MOVE_4: Drain Punch");
            GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_MOVE_4, mockConfidence);
        }

        if (Input.GetKeyDown(resetKey))
        {
            Debug.Log("[MockInput] RESET to Idle");
            GameStateManager.Instance.ResetToIdle();
        }
    }

#if UNITY_EDITOR
    private void OnGUI()
    {
        if (!enableMockInput) return;

        GUILayout.BeginArea(new Rect(10, 10, 300, 250));
        GUILayout.Label("=== MOCK INPUT (Debug) ===");
        GUILayout.Label($"State: {GameStateManager.Instance?.CurrentPhase}");
        GUILayout.Label($"Aiming: {(CatchManager.Instance?.IsAiming == true ? "YES" : "no")}");
        GUILayout.Label("");
        GUILayout.Label($"[{aimKey}] Aim (show reticle)");
        GUILayout.Label($"[{catchThrowKey}] Catch Throw (fire ball)");
        GUILayout.Label($"[{cancelKey}] Cancel (hide reticle)");
        GUILayout.Label($"[{battleEntryKey}] Battle Entry");
        GUILayout.Label($"[{move1Key}] Move 1: Close Combat");
        GUILayout.Label($"[{move2Key}] Move 2: Protect");
        GUILayout.Label($"[{move3Key}] Move 3: Brick Break");
        GUILayout.Label($"[{move4Key}] Move 4: Drain Punch");
        GUILayout.Label($"[{resetKey}] Reset to Idle");
        GUILayout.Label("");
        GUILayout.Label($"Network: {(NetworkManager.Instance?.IsConnected == true ? "Connected" : "Disconnected")}");
        GUILayout.EndArea();
    }
#endif
}
