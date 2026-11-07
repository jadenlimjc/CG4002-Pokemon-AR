using System.Collections;
using UnityEngine;
using TMPro;

public class TutorialOverlay : MonoBehaviour
{
    [Header("Tutorial Panel")]
    [SerializeField] private GameObject tutorialPanel;
    [SerializeField] private TextMeshProUGUI stepText;
    [SerializeField] private TextMeshProUGUI instructionText;
    [SerializeField] private TextMeshProUGUI feedbackText;

    [Header("Command Labels")]
    [SerializeField] private GameObject godModeLabel;
    [SerializeField] private GameObject fullPlayLabel;
    [SerializeField] private GameObject skipStepLabel;

    private Coroutine feedbackCoroutine;

    private void OnEnable()
    {
        if (TutorialManager.Instance != null)
        {
            TutorialManager.Instance.OnStepChanged += HandleStepChanged;
            TutorialManager.Instance.OnTutorialFeedback += HandleFeedback;
        }
        if (DemoModeManager.Instance != null)
            DemoModeManager.Instance.OnDemoModeChanged += HandleModeChanged;
    }

    private void Start()
    {
        if (TutorialManager.Instance != null)
        {
            TutorialManager.Instance.OnStepChanged -= HandleStepChanged;
            TutorialManager.Instance.OnStepChanged += HandleStepChanged;
            TutorialManager.Instance.OnTutorialFeedback -= HandleFeedback;
            TutorialManager.Instance.OnTutorialFeedback += HandleFeedback;
        }
        if (DemoModeManager.Instance != null)
        {
            DemoModeManager.Instance.OnDemoModeChanged -= HandleModeChanged;
            DemoModeManager.Instance.OnDemoModeChanged += HandleModeChanged;
        }

        Hide();
    }

    private void OnDisable()
    {
        if (TutorialManager.Instance != null)
        {
            TutorialManager.Instance.OnStepChanged -= HandleStepChanged;
            TutorialManager.Instance.OnTutorialFeedback -= HandleFeedback;
        }
        if (DemoModeManager.Instance != null)
            DemoModeManager.Instance.OnDemoModeChanged -= HandleModeChanged;
    }

    private void BuildUI()
    {
        overlayPanel = new GameObject("TutorialOverlay");
        overlayPanel.transform.SetParent(transform, false);

        RectTransform panelRect = overlayPanel.AddComponent<RectTransform>();
        panelRect.anchorMin = new Vector2(0f, 0.78f);
        panelRect.anchorMax = new Vector2(1f, 1f);
        panelRect.offsetMin = Vector2.zero;
        panelRect.offsetMax = Vector2.zero;

        Image bg = overlayPanel.AddComponent<Image>();
        bg.color = new Color(0.1f, 0.1f, 0.3f, 0.85f);

        // Step counter (top-left)
        stepText = CreateLabel(overlayPanel.transform, "StepText",
            new Vector2(0f, 0.7f), new Vector2(0.35f, 1f),
            new Vector2(15f, 0f), new Vector2(0f, -5f),
            stepFontSize, new Color(0.6f, 0.8f, 1f), TextAlignmentOptions.TopLeft);

        // Instruction text (middle area)
        instructionText = CreateLabel(overlayPanel.transform, "InstructionText",
            new Vector2(0f, 0.3f), new Vector2(1f, 0.72f),
            new Vector2(15f, 0f), new Vector2(-15f, 0f),
            instructionFontSize, Color.white, TextAlignmentOptions.MidlineLeft);
        instructionText.fontStyle = FontStyles.Bold;

        // Feedback text (top-center)
        feedbackText = CreateLabel(overlayPanel.transform, "FeedbackText",
            new Vector2(0.35f, 0.7f), new Vector2(0.7f, 1f),
            Vector2.zero, new Vector2(0f, -5f),
            stepFontSize, new Color(0.4f, 1f, 0.4f), TextAlignmentOptions.TopCenter);

        // Command labels row (bottom of overlay)
        float labelY0 = 0f;
        float labelY1 = 0.3f;

        CreateCommandLabel(overlayPanel.transform, "GOD MODE",
            new Vector2(0.02f, labelY0), new Vector2(0.34f, labelY1),
            new Color(0.9f, 0.7f, 0.1f, 0.8f));

        CreateCommandLabel(overlayPanel.transform, "FULL PLAY",
            new Vector2(0.35f, labelY0), new Vector2(0.67f, labelY1),
            new Color(0.3f, 0.8f, 0.4f, 0.8f));

        CreateCommandLabel(overlayPanel.transform, "SKIP STEP",
            new Vector2(0.68f, labelY0), new Vector2(0.98f, labelY1),
            new Color(0.5f, 0.5f, 0.8f, 0.8f));
    }

    private void CreateCommandLabel(Transform parent, string label,
        Vector2 anchorMin, Vector2 anchorMax, Color bgColor)
    {
        GameObject obj = new GameObject("Cmd_" + label);
        obj.transform.SetParent(parent, false);

        RectTransform rect = obj.AddComponent<RectTransform>();
        rect.anchorMin = anchorMin;
        rect.anchorMax = anchorMax;
        rect.offsetMin = new Vector2(2f, 2f);
        rect.offsetMax = new Vector2(-2f, -2f);

        Image img = obj.AddComponent<Image>();
        img.color = bgColor;

        GameObject textObj = new GameObject("Text");
        textObj.transform.SetParent(obj.transform, false);
        RectTransform textRect = textObj.AddComponent<RectTransform>();
        textRect.anchorMin = Vector2.zero;
        textRect.anchorMax = Vector2.one;
        textRect.offsetMin = Vector2.zero;
        textRect.offsetMax = Vector2.zero;

        TextMeshProUGUI tmp = textObj.AddComponent<TextMeshProUGUI>();
        tmp.text = label;
        tmp.fontSize = labelFontSize;
        tmp.color = Color.white;
        tmp.alignment = TextAlignmentOptions.Center;
        tmp.fontStyle = FontStyles.Bold;
    }

    private TextMeshProUGUI CreateLabel(Transform parent, string name,
        Vector2 anchorMin, Vector2 anchorMax, Vector2 offsetMin, Vector2 offsetMax,
        int fontSize, Color color, TextAlignmentOptions alignment)
    {
        GameObject obj = new GameObject(name);
        obj.transform.SetParent(parent, false);

        RectTransform rect = obj.AddComponent<RectTransform>();
        rect.anchorMin = anchorMin;
        rect.anchorMax = anchorMax;
        rect.offsetMin = offsetMin;
        rect.offsetMax = offsetMax;

        TextMeshProUGUI tmp = obj.AddComponent<TextMeshProUGUI>();
        tmp.fontSize = fontSize;
        tmp.color = color;
        tmp.alignment = alignment;
        return tmp;
    }

    private void HandleStepChanged(int stepIndex, TutorialManager.TutorialStep step)
    {
        Show();
        if (stepText != null)
            stepText.text = $"Step {stepIndex + 1} of {TutorialManager.Instance.TotalSteps}";
        if (instructionText != null)
            instructionText.text = step.instruction;
        if (feedbackText != null)
            feedbackText.text = "";
    }

    private void HandleFeedback(string message)
    {
        if (feedbackText == null) return;

        if (feedbackCoroutine != null)
            StopCoroutine(feedbackCoroutine);

        feedbackText.text = message;
        feedbackCoroutine = StartCoroutine(FadeFeedback());
    }

    private IEnumerator FadeFeedback()
    {
        if (feedbackText != null)
            feedbackText.color = new Color(feedbackText.color.r, feedbackText.color.g, feedbackText.color.b, 1f);

        yield return new WaitForSeconds(2f);

        float elapsed = 0f;
        float fadeDuration = 0.5f;
        Color original = feedbackText != null ? feedbackText.color : Color.white;

        while (elapsed < fadeDuration)
        {
            elapsed += Time.deltaTime;
            float alpha = 1f - (elapsed / fadeDuration);
            if (feedbackText != null)
                feedbackText.color = new Color(original.r, original.g, original.b, alpha);
            yield return null;
        }

        if (feedbackText != null)
            feedbackText.text = "";
    }

    private void HandleModeChanged(DemoMode oldMode, DemoMode newMode)
    {
        if (newMode == DemoMode.Tutorial)
            Show();
        else
            Hide();
    }

    private void Show()
    {
        if (tutorialPanel != null) tutorialPanel.SetActive(true);
        if (godModeLabel != null) godModeLabel.SetActive(true);
        if (fullPlayLabel != null) fullPlayLabel.SetActive(true);
        if (skipStepLabel != null) skipStepLabel.SetActive(true);
    }

    private void Hide()
    {
        if (tutorialPanel != null) tutorialPanel.SetActive(false);
        if (godModeLabel != null) godModeLabel.SetActive(false);
        if (fullPlayLabel != null) fullPlayLabel.SetActive(false);
        if (skipStepLabel != null) skipStepLabel.SetActive(false);
    }
}
