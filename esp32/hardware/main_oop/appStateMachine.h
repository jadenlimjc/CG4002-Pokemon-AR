#ifndef APP_STATE_MACHINE_H
#define APP_STATE_MACHINE_H

#include <Arduino.h>

// =====================================================
// AppStateMachine: owns currentState, both sub-modes,
// and all browse/cycle indices. Provides state-transition
// and reset methods so this logic lives in one place.
// =====================================================
enum AppState { STATE_EXPLORER, STATE_BATTLE, STATE_MENU };
enum BrowseSubMode { BROWSE_NORMAL, BROWSE_POKEMON, BROWSE_ITEM };

class AppStateMachine {
  public:
    static const int MOVE_COUNT = 4;
    static const int POKEMON_COUNT = 6;
    static const int ITEM_COUNT = 4;
    static const int MENU_OPTION_COUNT = 3;
    static const int EXPLORER_NORMAL_OPTION_COUNT = 3;

    AppState current = STATE_EXPLORER;
    BrowseSubMode battleSubMode = BROWSE_NORMAL;
    BrowseSubMode explorerSubMode = BROWSE_NORMAL;

    int battleMoveIndex = 0;
    int battlePokemonIndex = 0;
    int battleItemIndex = 0;
    int explorerNormalOptionIndex = 0;
    int menuOptionIndex = 0;

    static const char* stateToString(AppState s);
    static const char* subModeToString(BrowseSubMode m);

    // Middle finger: cycles Explorer -> Battle -> Menu -> Explorer.
    void cycleState();

    // Ring finger: cycles the browse target for whichever
    // state/sub-mode is currently active.
    void cycleRing();

    // Index finger select/exit. Returns true if a select/exit
    // actually happened (caller uses this to trigger haptics).
    bool handleIndexAction();

    void applySimulatedReach(char c);

    void printAll() const;

    void reset();
};

#endif // APP_STATE_MACHINE_H