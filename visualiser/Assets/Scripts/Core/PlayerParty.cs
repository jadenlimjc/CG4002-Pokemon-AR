using System;
using System.Collections.Generic;
using UnityEngine;

[Serializable]
public class PartyPokemon
{
    public PokemonData Data;
    public int CurrentHP;

    public PartyPokemon(PokemonData data)
    {
        Data = data;
        CurrentHP = data.maxHP;
    }

    public bool IsFainted => CurrentHP <= 0;
}

public class PlayerParty : MonoBehaviour
{
    public static PlayerParty Instance { get; private set; }

    public const int MaxPartySize = 6;

    [Header("Starter Pokemon")]
    [SerializeField] private PokemonData starterPokemon;

    [Header("Debug")]
    [SerializeField] private int leadIndex = 0;

    private List<PartyPokemon> party = new List<PartyPokemon>();

    public IReadOnlyList<PartyPokemon> Party => party;
    public int LeadIndex => leadIndex;
    public PartyPokemon LeadPokemon => party.Count > 0 ? party[leadIndex] : null;
    public int Count => party.Count;
    public bool IsFull => party.Count >= MaxPartySize;

    public delegate void PartyChangedHandler();
    public event PartyChangedHandler OnPartyChanged;

    private void Awake()
    {
        if (Instance != null && Instance != this)
        {
            Destroy(gameObject);
            return;
        }
        Instance = this;

        if (starterPokemon != null)
        {
            party.Add(new PartyPokemon(starterPokemon));
            leadIndex = 0;
        }
    }

    public bool AddPokemon(PokemonData data)
    {
        if (IsFull) return false;
        party.Add(new PartyPokemon(data));
        Debug.Log($"[Party] {data.pokemonName} added! Party size: {party.Count}/{MaxPartySize}");
        OnPartyChanged?.Invoke();
        return true;
    }

    public void SetLead(int index)
    {
        if (index < 0 || index >= party.Count) return;
        leadIndex = index;
        Debug.Log($"[Party] Lead set to {party[leadIndex].Data.pokemonName}");
        OnPartyChanged?.Invoke();
    }

    public void SaveHP(int hp)
    {
        if (LeadPokemon == null) return;
        LeadPokemon.CurrentHP = Mathf.Max(0, hp);
    }

    public bool HasUsablePokemon()
    {
        for (int i = 0; i < party.Count; i++)
        {
            if (i == leadIndex) continue;
            if (!party[i].IsFainted) return true;
        }
        return false;
    }

    public int FirstUsableIndex()
    {
        for (int i = 0; i < party.Count; i++)
        {
            if (i == leadIndex) continue;
            if (!party[i].IsFainted) return i;
        }
        return -1;
    }
}
