using UnityEngine;
using UnityEngine.UI;
using TMPro;

public class ModeSelectUI : MonoBehaviour
{
    public static ModeSelectUI Instance { get; private set; }

    [Header("Settings")]
    [SerializeField] private bool showOnStart = true;
    [SerializeField] private int titleFontSize = 28;
    [SerializeField] private int buttonFontSize = 20;
    [SerializeField] private int descFontSize = 14;

    private GameObject panel;
    private Canvas canvas;

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
        canvas = GetComponentInParent<Canvas>();
        if (canvas == null) return;

        BuildUI();

        if (showOnStart)
            Show();
        else
            Hide();
    }

    private void BuildUI()
    {
        panel = new GameObject("ModeSelectPanel");
        panel.transform.SetParent(transform, false);

        RectTransform panelRect = panel.AddComponent<RectTransform>();
        panelRect.anchorMin = Vector2.zero;
        panelRect.anchorMax = Vector2.one;
        panelRect.offsetMin = Vector2.zero;
        panelRect.offsetMax = Vector2.zero;

        Image bg = panel.AddComponent<Image>();
        bg.color = new Color(0f, 0f, 0f, 0.85f);

        // Title
        CreateText(panel.transform, "Select Demo Mode", titleFontSize,
            new Vector2(0.5f, 0.85f), new Vector2(0.5f, 0.85f), Color.white);

        // Mode buttons
        float buttonWidth = 500f;
        float buttonHeight = 100f;
        float startY = 0.65f;
        float spacing = 0.15f;

        CreateModeButton(panel.transform, "Tutorial",
            "Guided walkthrough with step-by-step training",
            DemoMode.Tutorial,
            new Color(0.2f, 0.6f, 0.9f, 0.9f),
            buttonWidth, buttonHeight, startY);

        CreateModeButton(panel.transform, "God Mode",
            "Play freely — you can't lose or miss a catch",
            DemoMode.GodMode,
            new Color(0.9f, 0.7f, 0.1f, 0.9f),
            buttonWidth, buttonHeight, startY - spacing);

        CreateModeButton(panel.transform, "Full Play",
            "Normal gameplay, no restrictions",
            DemoMode.FullPlay,
            new Color(0.3f, 0.8f, 0.4f, 0.9f),
            buttonWidth, buttonHeight, startY - spacing * 2);
    }

    private void CreateModeButton(Transform parent, string title, string description,
        DemoMode mode, Color color, float width, float height, float anchorY)
    {
        GameObject buttonObj = new GameObject(title + "Button");
        buttonObj.transform.SetParent(parent, false);

        RectTransform rect = buttonObj.AddComponent<RectTransform>();
        rect.anchorMin = new Vector2(0.5f, anchorY);
        rect.anchorMax = new Vector2(0.5f, anchorY);
        rect.pivot = new Vector2(0.5f, 0.5f);
        rect.sizeDelta = new Vector2(width, height);

        Image img = buttonObj.AddComponent<Image>();
        img.color = color;

        Button btn = buttonObj.AddComponent<Button>();
        ColorBlock colors = btn.colors;
        colors.normalColor = color;
        colors.highlightedColor = Color.Lerp(color, Color.white, 0.2f);
        colors.pressedColor = Color.Lerp(color, Color.white, 0.4f);
        btn.colors = colors;

        btn.onClick.AddListener(() =>
        {
            if (DemoModeManager.Instance != null)
                DemoModeManager.Instance.SetMode(mode);
            Hide();
        });

        // Title text
        GameObject titleObj = new GameObject("Title");
        titleObj.transform.SetParent(buttonObj.transform, false);
        RectTransform titleRect = titleObj.AddComponent<RectTransform>();
        titleRect.anchorMin = new Vector2(0f, 0.5f);
        titleRect.anchorMax = new Vector2(1f, 1f);
        titleRect.offsetMin = new Vector2(20f, 0f);
        titleRect.offsetMax = new Vector2(-20f, -5f);

        TextMeshProUGUI titleTmp = titleObj.AddComponent<TextMeshProUGUI>();
        titleTmp.text = title;
        titleTmp.fontSize = buttonFontSize;
        titleTmp.color = Color.white;
        titleTmp.alignment = TextAlignmentOptions.MidlineLeft;
        titleTmp.fontStyle = FontStyles.Bold;

        // Description text
        GameObject descObj = new GameObject("Description");
        descObj.transform.SetParent(buttonObj.transform, false);
        RectTransform descRect = descObj.AddComponent<RectTransform>();
        descRect.anchorMin = new Vector2(0f, 0f);
        descRect.anchorMax = new Vector2(1f, 0.5f);
        descRect.offsetMin = new Vector2(20f, 5f);
        descRect.offsetMax = new Vector2(-20f, 0f);

        TextMeshProUGUI descTmp = descObj.AddComponent<TextMeshProUGUI>();
        descTmp.text = description;
        descTmp.fontSize = descFontSize;
        descTmp.color = new Color(1f, 1f, 1f, 0.7f);
        descTmp.alignment = TextAlignmentOptions.MidlineLeft;
    }

    private void CreateText(Transform parent, string text, int fontSize,
        Vector2 anchorMin, Vector2 anchorMax, Color color)
    {
        GameObject textObj = new GameObject("Text_" + text);
        textObj.transform.SetParent(parent, false);

        RectTransform rect = textObj.AddComponent<RectTransform>();
        rect.anchorMin = anchorMin;
        rect.anchorMax = anchorMax;
        rect.pivot = new Vector2(0.5f, 0.5f);
        rect.sizeDelta = new Vector2(600f, 60f);

        TextMeshProUGUI tmp = textObj.AddComponent<TextMeshProUGUI>();
        tmp.text = text;
        tmp.fontSize = fontSize;
        tmp.color = color;
        tmp.alignment = TextAlignmentOptions.Center;
        tmp.fontStyle = FontStyles.Bold;
    }

    public void Show()
    {
        if (panel != null)
            panel.SetActive(true);
    }

    public void Hide()
    {
        if (panel != null)
            panel.SetActive(false);
    }

    public bool IsVisible => panel != null && panel.activeSelf;
}
