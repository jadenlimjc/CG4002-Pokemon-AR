#include "appStateMachine.h"

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
      explorerSubMode = BROWSE_NORMAL; //reset Explorer submode
      break;
  }
  Serial.print("State: ");
  Serial.print(stateToString(previous));
  Serial.print(" -> ");
  Serial.println(stateToString(current));
}

void AppStateMachine::cycleRing() {

  if (current == STATE_EXPLORER) { // Currently in EXPLORER STATE
    switch (explorerSubMode) {
      case BROWSE_NORMAL:
        explorerNormalOptionIndex = (explorerNormalOptionIndex + 1) % EXPLORER_NORMAL_OPTION_COUNT;
        Serial.print("Explorer (normal): option -> "); //does nothing, simulates different moves in explorer mode
        Serial.println(explorerNormalOptionIndex);
        break;
      case BROWSE_POKEMON:
        battlePokemonIndex = (battlePokemonIndex + 1) % POKEMON_COUNT;
        Serial.print("Explorer (browsing Pokemon, no select): -> ");
        Serial.println(battlePokemonIndex);
        break;
      case BROWSE_ITEM:
        battleItemIndex = (battleItemIndex + 1) % ITEM_COUNT;
        Serial.print("Explorer (browsing Item, no select): -> ");
        Serial.println(battleItemIndex);
        break;
    }

  } else if (current == STATE_BATTLE) { //Currently in BATTLE state
    switch (battleSubMode) {
      case BROWSE_NORMAL:
        battleMoveIndex = (battleMoveIndex + 1) % MOVE_COUNT;
        Serial.print("Battle (normal): Move option -> "); //does nothing, simulates different move in Battle mode
        Serial.println(battleMoveIndex);
        break;
      case BROWSE_POKEMON:
        battlePokemonIndex = (battlePokemonIndex + 1) % POKEMON_COUNT;
        Serial.print("Battle (Pokemon select): option -> ");
        Serial.println(battlePokemonIndex);
        break;
      case BROWSE_ITEM:
        battleItemIndex = (battleItemIndex + 1) % ITEM_COUNT;
        Serial.print("Battle (Item select): option -> ");
        Serial.println(battleItemIndex);
        break;
    }
  } else if (current == STATE_MENU) { // Currently in MENU state
    menuOptionIndex = (menuOptionIndex + 1) % MENU_OPTION_COUNT;
    Serial.print("Menu: settings option -> ");
    Serial.println(menuOptionIndex);
  }
}

bool AppStateMachine::handleIndexAction() { //Go back to normal state after pressing index button
  if (current == STATE_EXPLORER) {
    if (explorerSubMode != BROWSE_NORMAL) {
      explorerSubMode = BROWSE_NORMAL;
      Serial.println("Explorer: exiting browse -> back to normal mode");
      return true;
    }
    return false;
  }

  if (current == STATE_BATTLE && battleSubMode != BROWSE_NORMAL) {
    switch (battleSubMode) {
      case BROWSE_POKEMON:
        Serial.print("SELECT -> Pokemon ");
        Serial.println(battlePokemonIndex);
        break;
      case BROWSE_ITEM:
        Serial.print("SELECT -> Item ");
        Serial.println(battleItemIndex);
        break;
      default:
        break;
    }
    battleSubMode = BROWSE_NORMAL;
    Serial.println("Returning to normal battle mode");
    return true;
  }
  return false;
}

void AppStateMachine::applySimulatedReach(char c) {
  if (current != STATE_EXPLORER && current != STATE_BATTLE) return;

  BrowseSubMode &active = (current == STATE_EXPLORER) ? explorerSubMode : battleSubMode;
  const char* label = (current == STATE_EXPLORER) ? "Explorer" : "Battle";

  if (c == 'p' || c == 'P') {
    active = BROWSE_POKEMON;
    Serial.print("[SIMULATED MODEL] back pocket reach -> ");
    Serial.print(label); Serial.println(": Pokemon mode");
  } else if (c == 'i' || c == 'I') {
    active = BROWSE_ITEM;
    Serial.print("[SIMULATED MODEL] front pocket reach -> ");
    Serial.print(label); Serial.println(": Item mode");
  } else if (c == 'n' || c == 'N') {
    active = BROWSE_NORMAL;
    Serial.print("[SIMULATED MODEL] returning to normal -> ");
    Serial.println(label);
  }
}

void AppStateMachine::printAll() const {
  Serial.println("----------------------------------------------------------------");
  Serial.print("Current State: ");
  Serial.println(stateToString(current));
  Serial.print("Battle sub mode: ");
  Serial.println(subModeToString(battleSubMode));
  if (battleSubMode == BROWSE_NORMAL) {
    Serial.print("Battle move index: ");
    Serial.println(battleMoveIndex);
  }
  Serial.print("Explorer sub mode: ");
  Serial.println(subModeToString(explorerSubMode));
  if (explorerSubMode == BROWSE_NORMAL) {
    Serial.print("Explorer normal browsing index: ");
    Serial.println(explorerNormalOptionIndex);
  }
  Serial.print("Pokemon browsing index: ");
  Serial.println(battlePokemonIndex);
  Serial.print("Item browsing index: ");
  Serial.println(battleItemIndex);
  Serial.print("Menu browsing index: ");
  Serial.println(menuOptionIndex);
  Serial.println("----------------------------------------------------------------");
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