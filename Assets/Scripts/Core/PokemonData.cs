using System;
using UnityEngine;

[Serializable]
public enum PokemonType
{
    Normal, Fire, Water, Grass, Electric, Ice,
    Fighting, Poison, Ground, Flying, Psychic,
    Bug, Rock, Ghost, Dragon, Dark, Steel, Fairy
}

[Serializable]
public enum SpawnBehavior
{
    Ground,     // Walks/runs on AR plane
    Flying,     // Hovers above AR plane
    Stationary  // Stays in one spot
}

[CreateAssetMenu(fileName = "NewPokemon", menuName = "Pokemon/Pokemon Data")]
public class PokemonData : ScriptableObject
{
    [Header("Identity")]
    public string pokemonName;
    public int pokedexNumber;
    public PokemonType primaryType;
    public PokemonType secondaryType;

    [Header("Stats")]
    public int maxHP = 100;
    public int attack = 50;
    public int defense = 50;
    public int speed = 50;

    [Header("Spawn Settings")]
    public SpawnBehavior spawnBehavior = SpawnBehavior.Ground;
    public float spawnScale = 1f;
    public float moveSpeed = 1f;

    [Header("Catch Rate")]
    [Range(0f, 1f)]
    public float baseCatchRate = 0.5f;

    [Header("Moves (for player's Pokemon)")]
    public MoveData[] moves = new MoveData[4];

    [Header("Prefab")]
    public GameObject modelPrefab;
}

[Serializable]
public class MoveData
{
    public string moveName;
    public PokemonType moveType;
    public int power;
    public int accuracy;   // 0-100
    public bool isProtect; // special flag for Protect-like moves
    public string animationTrigger;
}
