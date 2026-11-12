using UnityEngine;

public class MockInputController : MonoBehaviour
{
    [Header("Enable/Disable")]
    [SerializeField] private bool enableMockInput = true;

    [Header("Mock Confidence")]
    [SerializeField] private float mockConfidence = 0.95f;

    private void OnGUI()
    {
        if (!enableMockInput) return;

        Event e = Event.current;
        if (e != null && e.isKey)
        {
            Debug.Log($"[MockInput] Event detected: type={e.type} key={e.keyCode}");
        }
        if (e != null && e.type == EventType.KeyDown)
        {
            switch (e.keyCode)
            {
                case KeyCode.A:
                    if (GameStateManager.Instance != null &&
                        GameStateManager.Instance.CurrentPhase == GamePhase.BattleActive)
                    {
                        Debug.Log("[MockInput] BATTLE_CATCH + ARM_PULLBACK triggered");
                        GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_CATCH, mockConfidence);
                    }
                    else
                    {
                        Debug.Log("[MockInput] ARM_PULLBACK triggered (show reticle)");
                    }
                    GestureEvents.RaiseGestureReceived(GestureAction.ARM_PULLBACK, mockConfidence);
                    break;
                case KeyCode.C:
                    Debug.Log("[MockInput] CATCH_THROW triggered");
                    GestureEvents.RaiseGestureReceived(GestureAction.CATCH_THROW, mockConfidence);
                    break;
                case KeyCode.X:
                    Debug.Log("[MockInput] CANCEL triggered (hide reticle)");
                    GestureEvents.RaiseGestureReceived(GestureAction.CANCEL, mockConfidence);
                    break;
                case KeyCode.B:
                    Debug.Log("[MockInput] BATTLE_THROW triggered (battle entry)");
                    GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_THROW, mockConfidence);
                    break;
                case KeyCode.Alpha1:
                    Debug.Log("[MockInput] BATTLE_MOVE_1: Close Combat");
                    GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_MOVE_1, mockConfidence);
                    break;
                case KeyCode.Alpha2:
                    Debug.Log("[MockInput] BATTLE_MOVE_2: Protect");
                    GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_MOVE_2, mockConfidence);
                    break;
                case KeyCode.Alpha3:
                    Debug.Log("[MockInput] BATTLE_MOVE_3: Brick Break");
                    GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_MOVE_3, mockConfidence);
                    break;
                case KeyCode.Alpha4:
                    Debug.Log("[MockInput] BATTLE_MOVE_4: Uppercut");
                    GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_MOVE_4, mockConfidence);
                    break;
                case KeyCode.F:
                    Debug.Log("[MockInput] BATTLE_RUN triggered");
                    GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_RUN, mockConfidence);
                    break;
                case KeyCode.V:
                    Debug.Log("[MockInput] PARTY_POKEMON triggered");
                    GestureEvents.RaiseGestureReceived(GestureAction.PARTY_POKEMON, mockConfidence);
                    break;
                case KeyCode.I:
                    Debug.Log("[MockInput] BATTLE_ITEM triggered");
                    GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_ITEM, mockConfidence);
                    break;
                case KeyCode.R:
                    Debug.Log("[MockInput] RESET to Idle");
                    GameStateManager.Instance.ResetToIdle();
                    break;
                case KeyCode.T:
                    Debug.Log("[MockInput] SET_TUTORIAL triggered");
                    GestureEvents.RaiseGestureReceived(GestureAction.SET_TUTORIAL, mockConfidence);
                    break;
                case KeyCode.G:
                    Debug.Log("[MockInput] SET_GOD_MODE triggered");
                    GestureEvents.RaiseGestureReceived(GestureAction.SET_GOD_MODE, mockConfidence);
                    break;
                case KeyCode.P:
                    Debug.Log("[MockInput] SET_FULL_PLAY triggered");
                    GestureEvents.RaiseGestureReceived(GestureAction.SET_FULL_PLAY, mockConfidence);
                    break;
                case KeyCode.S:
                    Debug.Log("[MockInput] SKIP_STEP triggered");
                    GestureEvents.RaiseGestureReceived(GestureAction.SKIP_STEP, mockConfidence);
                    break;
                case KeyCode.Q:
                    Debug.Log("[MockInput] Toggle PairingUI");
                    if (PairingUI.Instance != null)
                    {
                        if (PairingUI.Instance.IsVisible)
                            PairingUI.Instance.Hide();
                        else
                            PairingUI.Instance.Show();
                    }
                    break;
            }
        }

    }
}
