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
        CreateUtilityButtons();
    }

    private void CreateEncounterButtons()
    {
        float startY = -100f;
        float x = -buttonWidth / 2f - spacing;

        CreateButton("Aim", x, startY, () =>
        {
            GestureEvents.RaiseGestureReceived(GestureAction.ARM_PULLBACK, mockConfidence);
        });

        CreateButton("Catch Throw", x, startY - (buttonHeight + spacing), () =>
        {
            GestureEvents.RaiseGestureReceived(GestureAction.CATCH_THROW, mockConfidence);
        });

        CreateButton("Battle Entry", x, startY - (buttonHeight + spacing) * 2, () =>
        {
            GestureEvents.RaiseGestureReceived(GestureAction.POKEBALL_THROW, mockConfidence);
        });

        CreateButton("Cancel", x, startY - (buttonHeight + spacing) * 3, () =>
        {
            GestureEvents.RaiseGestureReceived(GestureAction.CANCEL, mockConfidence);
        });
    }

    private void CreateBattleButtons()
    {
        float startY = -100f;
        float x = buttonWidth / 2f + spacing;

        CreateButton("Move 1", x, startY, () =>
        {
            GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_MOVE_1, mockConfidence);
        });

        CreateButton("Move 2", x, startY - (buttonHeight + spacing), () =>
        {
            GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_MOVE_2, mockConfidence);
        });

        CreateButton("Move 3", x, startY - (buttonHeight + spacing) * 2, () =>
        {
            GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_MOVE_3, mockConfidence);
        });

        CreateButton("Move 4", x, startY - (buttonHeight + spacing) * 3, () =>
        {
            GestureEvents.RaiseGestureReceived(GestureAction.BATTLE_MOVE_4, mockConfidence);
        });
    }

    private void CreateUtilityButtons()
    {
        CreateButton("Reset", 0f, -100f - (buttonHeight + spacing) * 4, () =>
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
        rect.anchorMin = new Vector2(0.5f, 1f);
        rect.anchorMax = new Vector2(0.5f, 1f);
        rect.pivot = new Vector2(0.5f, 1f);
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
