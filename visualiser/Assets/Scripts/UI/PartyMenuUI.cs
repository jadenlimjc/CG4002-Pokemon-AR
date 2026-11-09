using UnityEngine;
using UnityEngine.UI;
using TMPro;

public class PartyMenuUI : MonoBehaviour
{
    public static PartyMenuUI Instance { get; private set; }

    [Header("Panel")]
    [SerializeField] private GameObject menuPanel;

    [Header("Party Slots (6)")]
    [SerializeField] private GameObject[] slotObjects = new GameObject[6];
    [SerializeField] private Image[] slotBackgrounds = new Image[6];
    [SerializeField] private Image[] slotSpriteImages = new Image[6];
    [SerializeField] private TextMeshProUGUI[] slotNameTexts = new TextMeshProUGUI[6];

    [Header("Button Hints")]
    [SerializeField] private GameObject buttonHintsPanel;
    [SerializeField] private Image indexButtonIcon;
    [SerializeField] private Image middleButtonIcon;
    [SerializeField] private Image ringButtonIcon;

    [Header("Slot Backgrounds")]
    [SerializeField] private Sprite slotBgUnselected;
    [SerializeField] private Sprite slotBgSelected;

    [Header("Colors")]
    [SerializeField] private Color normalColor = new Color(0.15f, 0.15f, 0.2f, 0.9f);
    [SerializeField] private Color selectedColor = new Color(0.3f, 0.4f, 0.7f, 0.95f);
    [SerializeField] private Color faintedColor = new Color(0.3f, 0.15f, 0.15f, 0.7f);
    [SerializeField] private Color activeColor = new Color(0.2f, 0.5f, 0.3f, 0.9f);

    private int selectedIndex = 0;
    private bool isOpen = false;
    private bool isBattleContext = false;
    private bool isForcedSwitch = false;

    public bool IsOpen => isOpen;

    public delegate void PokemonSelectedHandler(int partyIndex, bool isBattle);
    public event PokemonSelectedHandler OnPokemonSelected;

    public delegate void MenuClosedHandler();
    public event MenuClosedHandler OnMenuClosed;

    private void Awake()
    {
        if (Instance != null && Instance != this)
        {
            Destroy(gameObject);
            return;
        }
        Instance = this;
        Hide();
    }

    public void Show(bool battleContext, bool forcedSwitch = false)
    {
        if (PlayerParty.Instance == null || PlayerParty.Instance.Count == 0) return;

        isBattleContext = battleContext;
        isForcedSwitch = forcedSwitch;
        isOpen = true;
        selectedIndex = 0;

        RefreshSlots();
        if (menuPanel != null) menuPanel.SetActive(true);
        if (buttonHintsPanel != null) buttonHintsPanel.SetActive(true);
    }

    public void Hide()
    {
        isOpen = false;
        isForcedSwitch = false;
        if (menuPanel != null) menuPanel.SetActive(false);
        if (buttonHintsPanel != null) buttonHintsPanel.SetActive(false);
        OnMenuClosed?.Invoke();
    }

    private void RefreshSlots()
    {
        PlayerParty party = PlayerParty.Instance;
        if (party == null) return;

        for (int i = 0; i < slotObjects.Length; i++)
        {
            if (slotObjects[i] == null) continue;

            if (i < party.Count)
            {
                slotObjects[i].SetActive(true);
                PartyPokemon pm = party.Party[i];

                if (slotNameTexts[i] != null)
                    slotNameTexts[i].text = pm.Data.pokemonName;

                if (slotSpriteImages[i] != null)
                {
                    if (pm.Data.partySprite != null)
                    {
                        slotSpriteImages[i].sprite = pm.Data.partySprite;
                        slotSpriteImages[i].enabled = true;
                    }
                    else
                    {
                        slotSpriteImages[i].enabled = false;
                    }
                }

                UpdateSlotColor(i);
            }
            else
            {
                slotObjects[i].SetActive(false);
            }
        }
    }

    private void UpdateSlotColor(int index)
    {
        if (slotBackgrounds[index] == null) return;

        PlayerParty party = PlayerParty.Instance;
        if (party == null || index >= party.Count) return;

        PartyPokemon pm = party.Party[index];
        bool isSelected = index == selectedIndex;

        if (slotBgUnselected != null && slotBgSelected != null)
            slotBackgrounds[index].sprite = isSelected ? slotBgSelected : slotBgUnselected;

        if (pm.IsFainted)
            slotBackgrounds[index].color = isSelected
                ? Color.Lerp(faintedColor, selectedColor, 0.3f) : faintedColor;
        else if (index == party.LeadIndex && isBattleContext)
            slotBackgrounds[index].color = activeColor;
        else if (isSelected)
            slotBackgrounds[index].color = selectedColor;
        else
            slotBackgrounds[index].color = normalColor;
    }

    private void Update()
    {
        if (!isOpen) return;

        PollGloveButtons();
        PollKeyboard();
    }

    private void PollGloveButtons()
    {
        if (NetworkManager.Instance == null) return;
        if (!NetworkManager.Instance.TryConsumeMenuControls(out bool middle, out bool index, out bool ring))
            return;

        if (index) CycleSelection();
        if (middle) ConfirmSelection();
        if (ring && !isForcedSwitch) Hide();
    }

    private void PollKeyboard()
    {
        if (Input.GetKeyDown(KeyCode.DownArrow))
            CycleSelection();
        if (Input.GetKeyDown(KeyCode.Return) || Input.GetKeyDown(KeyCode.E))
            ConfirmSelection();
        if (Input.GetKeyDown(KeyCode.Escape) && !isForcedSwitch)
            Hide();
    }

    private void CycleSelection()
    {
        PlayerParty party = PlayerParty.Instance;
        if (party == null) return;

        int oldIndex = selectedIndex;
        selectedIndex = (selectedIndex + 1) % party.Count;

        UpdateSlotColor(oldIndex);
        UpdateSlotColor(selectedIndex);
    }

    private void ConfirmSelection()
    {
        PlayerParty party = PlayerParty.Instance;
        if (party == null) return;

        PartyPokemon selected = party.Party[selectedIndex];

        if (selected.IsFainted)
        {
            Debug.Log("[PartyMenu] Can't select fainted pokemon");
            return;
        }

        if (isBattleContext && selectedIndex == party.LeadIndex)
        {
            Debug.Log("[PartyMenu] Can't switch to already active pokemon");
            return;
        }

        OnPokemonSelected?.Invoke(selectedIndex, isBattleContext);
        Hide();
    }
}
