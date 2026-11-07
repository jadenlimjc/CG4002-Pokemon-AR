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
