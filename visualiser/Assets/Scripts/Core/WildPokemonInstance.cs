using UnityEngine;

public class WildPokemonInstance
{
    private static int _nextId = 0;

    public int Id { get; }
    public GameObject GameObject { get; }
    public PokemonData Data { get; }
    public Animator Animator { get; }
    public string SpawnTerrain { get; }

    public WildPokemonInstance(GameObject gameObject, PokemonData data, string spawnTerrain)
    {
        Id = _nextId++;
        GameObject = gameObject;
        Data = data;
        Animator = gameObject.GetComponent<Animator>();
        SpawnTerrain = spawnTerrain;
    }
}
