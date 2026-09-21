using UnityEngine;
using UnityEngine.UI;
using TMPro;

public class OnScreenControls : MonoBehaviour
{
    [Header("Settings")]
    [SerializeField] private float mockConfidence = 0.95f;
    [SerializeField] private int buttonFontSize = 14;
    [SerializeField] private float buttonWidth = 150f;
    [SerializeField] private float buttonHeight = 50f;
    [SerializeField] private float spacing = 10f;

    private Canvas canvas;

    private void Start()
    {
        canvas = GetComponentInParent<Canvas>();
        if (canvas == null) return;

        CreateEncounterButtons();
        CreateBattleButtons();
        CreateBattleActionButtons();
        CreateUtilityButtons();
    }

    private void CreateEncounterButtons()
    {
        float y = buttonHeight + spacing;
        float leftX = -buttonWidth - spacing / 2f;

        CreateButton("Aim", leftX, y, () =>
        {
            GestureEvents.RaiseGestureReceived(GestureAction.ARM_PULLBACK, mockConfidence);
        });

        CreateButton("Catch Throw", leftX, y + (buttonHeight + spacing), () =>
        {
            GestureEvents.RaiseGestureReceived(GestureAction.CATCH_THROW, mockConfidence);
        });

        CreateButton("Battle Throw", leftX, y + (buttonHeight + spacing) * 2, () =>
        {
            GestureEvents.RaiseGestureReceived(GestureAction.POKEBALL_THROW, mockConfidence);
        });

        CreateButton("Cancel", leftX, y + (buttonHeight + spacing) * 3, () =>
        {
            GestureEvents.RaiseGestureReceived(GestureAction.CANCEL, mockConfidence);
        });
    }

    private void CreateBattleButtons()
    {
        float y = buttonHeight + spacing;
        float rightX = spacing / 2f;

        CreateButton("Move 1", rightX, y, () =>
        {
            GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_MOVE_1, mockConfidence);
        });

        CreateButton("Move 2", rightX, y + (buttonHeight + spacing), () =>
        {
            GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_MOVE_2, mockConfidence);
        });

        CreateButton("Move 3", rightX, y + (buttonHeight + spacing) * 2, () =>
        {
            GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_MOVE_3, mockConfidence);
        });

        CreateButton("Move 4", rightX, y + (buttonHeight + spacing) * 3, () =>
        {
            GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_MOVE_4, mockConfidence);
        });
    }

    private void CreateBattleActionButtons()
    {
        float y = buttonHeight + spacing;
        float farRightX = buttonWidth + spacing * 1.5f;

        CreateButton("Run", farRightX, y, () =>
        {
            GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_RUN, mockConfidence);
        });

        CreateButton("Switch", farRightX, y + (buttonHeight + spacing), () =>
        {
            GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_SWITCH, mockConfidence);
        });

        CreateButton("Item", farRightX, y + (buttonHeight + spacing) * 2, () =>
        {
            GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_ITEM, mockConfidence);
        });

        CreateButton("Catch", farRightX, y + (buttonHeight + spacing) * 3, () =>
        {
            GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_CATCH, mockConfidence);
        });
    }

    private void CreateUtilityButtons()
    {
        float y = buttonHeight + spacing + (buttonHeight + spacing) * 4;
        CreateButton("Reset", -buttonWidth / 2f, y, () =>
        {
            if (GameStateManager.Instance != null)
                GameStateManager.Instance.ResetToIdle();
        });
    }

    private void CreateButton(string label, float x, float y, UnityEngine.Events.UnityAction onClick)
    {
        GameObject buttonObj = new GameObject(label + "Button");
        buttonObj.transform.SetParent(transform, false);

        RectTransform rect = buttonObj.AddComponent<RectTransform>();
        rect.anchorMin = new Vector2(0.5f, 0f);
        rect.anchorMax = new Vector2(0.5f, 0f);
        rect.pivot = new Vector2(0f, 0f);
        rect.anchoredPosition = new Vector2(x, y);
        rect.sizeDelta = new Vector2(buttonWidth, buttonHeight);

        Image img = buttonObj.AddComponent<Image>();
        img.color = new Color(0.2f, 0.2f, 0.2f, 0.7f);

        Button btn = buttonObj.AddComponent<Button>();
        btn.onClick.AddListener(onClick);

        ColorBlock colors = btn.colors;
        colors.normalColor = new Color(0.2f, 0.2f, 0.2f, 0.7f);
        colors.highlightedColor = new Color(0.3f, 0.3f, 0.3f, 0.8f);
        colors.pressedColor = new Color(0.5f, 0.5f, 0.5f, 0.9f);
        btn.colors = colors;

        GameObject textObj = new GameObject("Text");
        textObj.transform.SetParent(buttonObj.transform, false);

        RectTransform textRect = textObj.AddComponent<RectTransform>();
        textRect.anchorMin = Vector2.zero;
        textRect.anchorMax = Vector2.one;
        textRect.offsetMin = Vector2.zero;
        textRect.offsetMax = Vector2.zero;

        TextMeshProUGUI tmp = textObj.AddComponent<TextMeshProUGUI>();
        tmp.text = label;
        tmp.fontSize = buttonFontSize;
        tmp.color = Color.white;
        tmp.alignment = TextAlignmentOptions.Center;
    }
}
