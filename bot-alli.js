// bot-alli.js
// AlliBot-style strategy adapted from alli.java to the RTSArena command API.

class AlliBot {
  constructor(playerId) {
    this.playerId = playerId;
  }

  getCommands(gs) {
    this._classify(gs);
    const cmds = [];

    const harvestCount = this._desiredHarvesters(gs);
    if (harvestCount > 0) {
      cmds.push({ type: "harvest", count: harvestCount });
    }

    if (this._shouldBuildBarracks(gs)) {
      cmds.push({ type: "build", buildingType: "barracks" });
    }

    this._produceUnits(gs, cmds);

    const target = this._pickCombatTarget(gs);
    if (target && this._shouldAttack(gs)) {
      cmds.push({ type: "attack", x: target.x, y: target.y });
    } else {
      cmds.push({ type: "defend" });
    }

    return cmds;
  }

  _classify(gs) {
    this.myBases = gs.myUnits.filter((u) => u.isBuilding && u.type === "base");
    this.myBarracks = gs.myUnits.filter((u) => u.isBuilding && u.type === "barracks");
    this.myWorkers = gs.myUnits.filter((u) => u.type === "worker");
    this.myHeavies = gs.myUnits.filter((u) => u.type === "heavy");
    this.myRanged = gs.myUnits.filter((u) => u.type === "ranged");
    this.myLights = gs.myUnits.filter((u) => u.type === "light");
    this.myArmy = gs.myUnits.filter((u) => !u.isBuilding && u.type !== "worker");

    this.enemyBases = gs.enemyUnits.filter((u) => u.isBuilding && u.type === "base");
    this.enemyBarracks = gs.enemyUnits.filter((u) => u.isBuilding && u.type === "barracks");
    this.enemyWorkers = gs.enemyUnits.filter((u) => u.type === "worker");
    this.enemyHeavies = gs.enemyUnits.filter((u) => u.type === "heavy");
    this.enemyRanged = gs.enemyUnits.filter((u) => u.type === "ranged");
    this.enemyLights = gs.enemyUnits.filter((u) => u.type === "light");
    this.enemyArmy = gs.enemyUnits.filter((u) => !u.isBuilding && u.type !== "worker");

    this.mapSize = this._inferMapSize(gs);
    this.myCombatPower = this._sumDamage(this.myArmy);
    this.enemyCombatPower = this._sumDamage(this.enemyArmy);
  }

  _inferMapSize(gs) {
    if (typeof gs.mapSize === "number") return gs.mapSize;
    if (Array.isArray(gs.terrain) && gs.terrain.length > 0) {
      if (Array.isArray(gs.terrain[0])) return gs.terrain.length;
      const n = Math.floor(Math.sqrt(gs.terrain.length));
      if (n > 0) return n;
    }
    return 16;
  }

  _desiredHarvesters(gs) {
    if (this.myWorkers.length === 0) return 0;

    const baseCount = Math.max(1, this.myBases.length);
    let perBase = 2;

    const totalWorkers = this.myWorkers.length + this.enemyWorkers.length;
    const totalCombat = this.myArmy.length + this.enemyArmy.length;
    const baseTotal = this.myBases.length + this.enemyBases.length;
    const barracksTotal = this.myBarracks.length + this.enemyBarracks.length;
    const area = this.mapSize * this.mapSize;
    const totalOcc = totalWorkers + totalCombat + baseTotal + barracksTotal;

    if (this.mapSize <= 12 && totalOcc > area / 2.9) {
      perBase = 1;
    }

    // alli.java lets workers join combat on smaller maps / low-tech states.
    if (this._shouldWorkersAttack(gs)) {
      perBase = Math.min(perBase, 1);
    }

    return Math.max(1, Math.min(this.myWorkers.length, perBase * baseCount));
  }

  _shouldBuildBarracks(gs) {
    const cost = this._cost("barracks");
    if (this.myWorkers.length === 0) return false;
    if (this.myBases.length === 0) return false;
    if (gs.myResources < cost) return false;
    if (this.myBarracks.length >= this.myBases.length) return false;
    return true;
  }

  _workerTarget(gs) {
    const baseCount = Math.max(1, this.myBases.length);
    if (this.mapSize < 9) return 15;
    if (this.mapSize > 16) return 2 * baseCount;
    if (gs.turn > 1000) return 2 * baseCount;

    const enemyPerBase = Math.floor(this.enemyWorkers.length / Math.max(1, this.enemyBases.length));
    return Math.max(2, enemyPerBase) * baseCount;
  }

  _produceUnits(gs, cmds) {
    const workerCost = this._cost("worker");
    const workerTarget = this._workerTarget(gs);

    if (this.myWorkers.length < workerTarget && gs.myResources >= workerCost) {
      const count = Math.max(1, Math.min(this.myBases.length || 1, workerTarget - this.myWorkers.length));
      cmds.push({ type: "train", unitType: "worker", count });
    }

    if (this.myBarracks.length === 0) return;

    const unitType = this._pickCombatUnit(gs);
    const unitCost = this._cost(unitType);
    if (gs.myResources < unitCost) return;

    const maxByFunds = Math.floor(gs.myResources / unitCost);
    const maxByBarracks = Math.max(1, this.myBarracks.length * 2);
    const count = Math.max(1, Math.min(maxByFunds, maxByBarracks));
    cmds.push({ type: "train", unitType, count });
  }

  _pickCombatUnit(gs) {
    // alli.java: heavy first, ranged fallback when enemy heavies are weak.
    if (this.enemyHeavies.length >= 2) return "ranged";
    if (this._enemyHeaviesWeak(gs)) return "ranged";
    if (gs.myResources >= this._cost("heavy")) return "heavy";
    if (gs.myResources >= this._cost("ranged")) return "ranged";
    return "light";
  }

  _enemyHeaviesWeak(gs) {
    if (this.enemyHeavies.length > 1) return false;
    if (this.enemyHeavies.length === 1 && (this.enemyHeavies[0].hp || 0) > 3) return false;
    const estEnemyRes = (gs.enemyResources || 0) + Math.min(2, this.enemyWorkers.length);
    return estEnemyRes < this._cost("heavy");
  }

  _shouldWorkersAttack(gs) {
    if (this.mapSize <= 12) return true;
    if (
      this._enemyHeaviesWeak(gs) &&
      this.enemyRanged.length === 0 &&
      this.myHeavies.length === 0 &&
      this.myRanged.length === 0
    ) {
      return true;
    }
    return false;
  }

  _shouldAttack(gs) {
    if (gs.enemyUnits.length === 0) return false;
    if (this._overPowering()) return true;
    if (this.myArmy.length > 0) return true;
    if (this._shouldWorkersAttack(gs) && this.myWorkers.length > 0) return true;
    return this._underAttack();
  }

  _underAttack() {
    if (this.myBases.length === 0) return false;
    const base = this.myBases[0];
    const enemyCombat = this.enemyArmy.concat(this.enemyWorkers);
    return enemyCombat.some((u) => this._manhattan(u, base) <= 6);
  }

  _pickCombatTarget(gs) {
    const enemies = gs.enemyUnits;
    if (enemies.length === 0) return null;

    const fighters = this.myArmy.length > 0 ? this.myArmy : this.myWorkers;
    const center = this._centroid(fighters);

    let best = null;
    let bestScore = -Infinity;

    for (const e of enemies) {
      let score = -this._manhattan(e, center);

      if (this.mapSize >= 16 && (this.myHeavies.length > 0 || this.myRanged.length > 0) && e.isBuilding && e.type === "barracks") {
        score += this.mapSize;
      }

      if (this.myRanged.length > 0 && e.type === "ranged" && this.mapSize > 9) {
        score += 2;
      }

      if (!e.isBuilding && (e.hp || 0) <= 2) {
        score += 2;
      }

      if (score > bestScore) {
        bestScore = score;
        best = e;
      }
    }

    return best;
  }

  _overPowering() {
    return this.myCombatPower > 1.2 * this.enemyCombatPower;
  }

  _centroid(units) {
    if (!units || units.length === 0) {
      const mid = Math.floor(this.mapSize / 2);
      return { x: mid, y: mid };
    }
    const sx = units.reduce((s, u) => s + u.x, 0);
    const sy = units.reduce((s, u) => s + u.y, 0);
    return { x: sx / units.length, y: sy / units.length };
  }

  _manhattan(a, b) {
    return Math.abs((a.x || 0) - (b.x || 0)) + Math.abs((a.y || 0) - (b.y || 0));
  }

  _sumDamage(units) {
    return units.reduce((s, u) => s + (u.damage || 1), 0);
  }

  _cost(unitType) {
    const stats = (typeof RTSArena !== "undefined" && RTSArena.UNIT_STATS) ? RTSArena.UNIT_STATS : null;
    if (!stats || !stats[unitType]) {
      const fallback = {
        worker: 1,
        base: 10,
        barracks: 5,
        light: 2,
        ranged: 3,
        heavy: 4,
      };
      return fallback[unitType] || 1;
    }
    return stats[unitType].cost;
  }
}

// Browser/global runner compatibility:
if (typeof window !== "undefined") {
  window.AlliBot = AlliBot;
}
if (typeof globalThis !== "undefined") {
  globalThis.AlliBot = AlliBot;
}

// RTSArena loader registration:
if (typeof RTSArena !== "undefined" && typeof RTSArena.registerBot === "function") {
  RTSArena.registerBot("alliBot", AlliBot);
}

// Node-style export compatibility:
if (typeof module !== "undefined" && module.exports) {
  module.exports = AlliBot;
}
