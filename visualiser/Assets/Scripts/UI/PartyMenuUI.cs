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

                UpdateSlotVisual(i);
            }
            else
            {
                slotObjects[i].SetActive(false);
            }
        }
    }

    private void UpdateSlotVisual(int index)
    {
        if (slotBackgrounds[index] == null) return;

        PlayerParty party = PlayerParty.Instance;
        if (party == null || index >= party.Count) return;

        bool isSelected = index == selectedIndex;

        if (slotBgUnselected != null && slotBgSelected != null)
            slotBackgrounds[index].sprite = isSelected ? slotBgSelected : slotBgUnselected;

        slotBackgrounds[index].color = Color.white;
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

        UpdateSlotVisual(oldIndex);
        UpdateSlotVisual(selectedIndex);
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
