#include "appStateMachine.h"
#include "DualPrint.h"

const char* AppStateMachine::stateToString(AppState s) {
  switch (s) {
    case STATE_EXPLORER: return "EXPLORER";
    case STATE_BATTLE:   return "BATTLE";
    case STATE_MENU:     return "MENU";
    default:             return "UNKNOWN";
  }
}

const char* AppStateMachine::subModeToString(BrowseSubMode m) {
  switch (m) {
    case BROWSE_NORMAL:  return "NORMAL";
    case BROWSE_POKEMON: return "POKEMON";
    case BROWSE_ITEM:    return "ITEM";
    default:             return "UNKNOWN";
  }
}

void AppStateMachine::cycleState() {
  AppState previous = current;
  switch (current) {

    case STATE_EXPLORER:
      current = STATE_BATTLE;
      battleSubMode = BROWSE_NORMAL; //reset battle submode
      break;
    case STATE_BATTLE:
      current = STATE_MENU;
      break;
    case STATE_MENU:
      current = STATE_EXPLORER;
      explorerSubMode = BROWSE_NORMAL; //reset explorer submode
      break;
  }
  dbg.print("State: ");
  dbg.print(stateToString(previous));
  dbg.print(" -> ");
  dbg.println(stateToString(current));
}

void AppStateMachine::cycleRing() {

  if (current == STATE_EXPLORER) { // Currently in EXPLORER STATE
    switch (explorerSubMode) {
      case BROWSE_NORMAL:
        explorerNormalOptionIndex = (explorerNormalOptionIndex + 1) % EXPLORER_NORMAL_OPTION_COUNT;
        dbg.print("Explorer (normal): option -> "); //does nothing, simulates different moves in explorer mode
        dbg.println(explorerNormalOptionIndex);
        break;
      case BROWSE_POKEMON:
        battlePokemonIndex = (battlePokemonIndex + 1) % POKEMON_COUNT;
        dbg.print("Explorer (browsing Pokemon, no select): -> ");
        dbg.println(battlePokemonIndex);
        break;
      case BROWSE_ITEM:
        battleItemIndex = (battleItemIndex + 1) % ITEM_COUNT;
        dbg.print("Explorer (browsing Item, no select): -> ");
        dbg.println(battleItemIndex);
        break;
    }

  } else if (current == STATE_BATTLE) { //Currently in BATTLE state
    switch (battleSubMode) {
      case BROWSE_NORMAL:
        battleMoveIndex = (battleMoveIndex + 1) % MOVE_COUNT;
        dbg.print("Battle (normal): Move option -> "); //does nothing, simulates different move in Battle mode
        dbg.println(battleMoveIndex);
        break;
      case BROWSE_POKEMON:
        battlePokemonIndex = (battlePokemonIndex + 1) % POKEMON_COUNT;
        dbg.print("Battle (Pokemon select): option -> ");
        dbg.println(battlePokemonIndex);
        break;
      case BROWSE_ITEM:
        battleItemIndex = (battleItemIndex + 1) % ITEM_COUNT;
        dbg.print("Battle (Item select): option -> ");
        dbg.println(battleItemIndex);
        break;
    }
  } else if (current == STATE_MENU) { // Currently in MENU state
    menuOptionIndex = (menuOptionIndex + 1) % MENU_OPTION_COUNT;
    dbg.print("Menu: settings option -> ");
    dbg.println(menuOptionIndex);
  }
}

bool AppStateMachine::handleIndexAction() { 
  if (current == STATE_EXPLORER) { //Go back to normal state after pressing index button
    if (explorerSubMode != BROWSE_NORMAL) {
      explorerSubMode = BROWSE_NORMAL;
      dbg.println("Explorer: exiting browse -> back to normal mode");
      return true;
    }
    return false;
  }

  if (current == STATE_BATTLE && battleSubMode != BROWSE_NORMAL) { //Go back to normal state after pressing index button
    switch (battleSubMode) { // select based on submode in BATTLE state
      case BROWSE_POKEMON:
        dbg.print("SELECT -> Pokemon ");
        dbg.println(battlePokemonIndex);
        break;
      case BROWSE_ITEM:
        dbg.print("SELECT -> Item ");
        dbg.println(battleItemIndex);
        break;
      default:
        break;
    }
    battleSubMode = BROWSE_NORMAL; 
    dbg.println("Returning to normal battle mode");
    return true;
  }
  return false;
}

void AppStateMachine::applySimulatedReach(char c) { //simulate Fron
  if (current != STATE_EXPLORER && current != STATE_BATTLE) return;

  BrowseSubMode &active = (current == STATE_EXPLORER) ? explorerSubMode : battleSubMode;
  const char* label = (current == STATE_EXPLORER) ? "Explorer" : "Battle";

  if (c == 'p' || c == 'P') {
    active = BROWSE_POKEMON;
    dbg.print("[SIMULATED MODEL] back pocket reach -> ");
    dbg.print(label); dbg.println(": Pokemon mode");
  } else if (c == 'i' || c == 'I') {
    active = BROWSE_ITEM;
    dbg.print("[SIMULATED MODEL] front pocket reach -> ");
    dbg.print(label); dbg.println(": Item mode");
  } else if (c == 'n' || c == 'N') {
    active = BROWSE_NORMAL;
    dbg.print("[SIMULATED MODEL] returning to normal -> ");
    dbg.println(label);
  }
}

void AppStateMachine::printAll() const {
  dbg.println("----------------------------------------------------------------");
  dbg.print("Current State: ");
  dbg.println(stateToString(current));
  dbg.print("Battle sub mode: ");
  dbg.println(subModeToString(battleSubMode));
  if (battleSubMode == BROWSE_NORMAL) {
    dbg.print("Battle move index: ");
    dbg.println(battleMoveIndex);
  }
  dbg.print("Explorer sub mode: ");
  dbg.println(subModeToString(explorerSubMode));
  if (explorerSubMode == BROWSE_NORMAL) {
    dbg.print("Explorer normal browsing index: ");
    dbg.println(explorerNormalOptionIndex);
  }
  dbg.print("Pokemon browsing index: ");
  dbg.println(battlePokemonIndex);
  dbg.print("Item browsing index: ");
  dbg.println(battleItemIndex);
  dbg.print("Menu browsing index: ");
  dbg.println(menuOptionIndex);
  dbg.println("----------------------------------------------------------------");
}

void AppStateMachine::reset() {
  current = STATE_EXPLORER;
  battleSubMode = BROWSE_NORMAL;
  explorerSubMode = BROWSE_NORMAL;
  battleMoveIndex = 0;
  battlePokemonIndex = 0;
  battleItemIndex = 0;
  explorerNormalOptionIndex = 0;
  menuOptionIndex = 0;
}