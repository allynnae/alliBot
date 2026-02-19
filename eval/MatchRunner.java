package eval;

import ai.core.AI;
import java.lang.reflect.Constructor;
import rts.GameState;
import rts.PhysicalGameState;
import rts.PlayerAction;
import rts.units.UnitTypeTable;

/**
 * Runs one headless MicroRTS match and prints a single-line JSON result.
 *
 * Args:
 *   0: map XML path
 *   1: max cycles
 *   2: UTT version
 *   3: conflict policy
 *   4: ai1 class
 *   5: ai2 class
 */
public class MatchRunner {

    private static class Result {
        int winner;
        int cycles;
        boolean gameOver;
    }

    public static void main(String[] args) throws Exception {
        if (args.length < 6) {
            System.err.println(
                "Usage: eval.MatchRunner <map> <maxCycles> <uttVersion> <conflictPolicy> <ai1> <ai2>");
            System.exit(2);
        }

        String mapPath = args[0];
        int maxCycles = Integer.parseInt(args[1]);
        int uttVersion = Integer.parseInt(args[2]);
        int conflictPolicy = Integer.parseInt(args[3]);
        String ai1Class = args[4];
        String ai2Class = args[5];

        Result result = runMatch(mapPath, maxCycles, uttVersion, conflictPolicy, ai1Class, ai2Class);
        System.out.println(
            "{\"winner\":" + result.winner
            + ",\"cycles\":" + result.cycles
            + ",\"game_over\":" + result.gameOver + "}");
    }

    private static Result runMatch(
        String mapPath,
        int maxCycles,
        int uttVersion,
        int conflictPolicy,
        String ai1Class,
        String ai2Class
    ) throws Exception {
        UnitTypeTable utt = new UnitTypeTable(uttVersion, conflictPolicy);
        PhysicalGameState pgs = PhysicalGameState.load(mapPath, utt);
        GameState gs = new GameState(pgs, utt);

        AI ai1 = instantiate(ai1Class, utt);
        AI ai2 = instantiate(ai2Class, utt);

        ai1.reset();
        ai2.reset();

        ai1.preGameAnalysis(gs, 0);
        ai2.preGameAnalysis(gs, 0);

        boolean gameOver = false;
        while (!gameOver && gs.getTime() < maxCycles) {
            PlayerAction pa1 = ai1.getAction(0, gs);
            PlayerAction pa2 = ai2.getAction(1, gs);
            gs.issueSafe(pa1);
            gs.issueSafe(pa2);
            gameOver = gs.cycle();
        }

        int winner = gs.winner();
        ai1.gameOver(winner);
        ai2.gameOver(winner);

        Result out = new Result();
        out.winner = winner;
        out.cycles = gs.getTime();
        out.gameOver = gameOver;
        return out;
    }

    private static AI instantiate(String className, UnitTypeTable utt) throws Exception {
        Class<?> clazz = Class.forName(className);
        Constructor<?> ctor = clazz.getConstructor(UnitTypeTable.class);
        return (AI) ctor.newInstance(utt);
    }
}
