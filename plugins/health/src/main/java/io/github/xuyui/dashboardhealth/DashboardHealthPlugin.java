package io.github.xuyui.dashboardhealth;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import java.io.IOException;
import java.lang.management.ManagementFactory;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.logging.Level;
import org.bukkit.Server;
import org.bukkit.World;
import org.bukkit.plugin.java.JavaPlugin;
import xyz.jpenilla.squaremap.api.SquaremapProvider;

/**
 * Writes the server's health (TPS, tick time, memory, CPU, loaded chunks and entities) to
 * dashboard/health.json in squaremap's web directory every few seconds, with an hour of
 * per-minute history, for the dashboard's status bar.
 *
 * <p>When the server is paused because nobody is online (pause-when-empty-seconds), ticks and
 * this task stop too; the file's timestamp then goes stale and the page shows "idle".
 */
public final class DashboardHealthPlugin extends JavaPlugin {
    private static final int HISTORY_MINUTES = 60;

    private final Gson gson = new GsonBuilder().create();
    private final ArrayDeque<Map<String, Object>> history = new ArrayDeque<>();
    private final Object writeLock = new Object();
    private Path out;
    private long lastHistoryMinute = -1;

    @Override
    public void onEnable() {
        saveDefaultConfig();
        Path web = SquaremapProvider.get().webDir();
        out = web.resolve(getConfig().getString("output", "dashboard/health.json"));
        long period = Math.max(20L, getConfig().getLong("interval-seconds", 5) * 20L);
        // Sampling reads world state, so it runs on the main thread; writing happens off it.
        getServer().getScheduler().runTaskTimer(this, this::sample, 40L, period);
    }

    private void sample() {
        Server server = getServer();
        double[] tps = server.getTPS();
        int chunks = 0;
        int entities = 0;
        for (World world : server.getWorlds()) {
            chunks += world.getChunkCount();
            entities += world.getEntityCount();
        }
        Runtime rt = Runtime.getRuntime();
        long used = rt.totalMemory() - rt.freeMemory();
        double processCpu = -1;
        double systemCpu = -1;
        if (ManagementFactory.getOperatingSystemMXBean() instanceof com.sun.management.OperatingSystemMXBean os) {
            processCpu = os.getProcessCpuLoad();
            systemCpu = os.getCpuLoad();
        }
        long now = System.currentTimeMillis();

        Map<String, Object> s = new LinkedHashMap<>();
        s.put("ts", now);
        s.put("tps", new double[] {round(tps[0]), round(tps[1]), round(tps[2])});
        s.put("mspt", round(server.getAverageTickTime()));
        s.put("mem_used", used);
        s.put("mem_max", rt.maxMemory());
        s.put("cpu_process", round(processCpu * 100));
        s.put("cpu_system", round(systemCpu * 100));
        s.put("cores", rt.availableProcessors());
        s.put("players", server.getOnlinePlayers().size());
        s.put("chunks", chunks);
        s.put("entities", entities);

        long minute = now / 60000;
        if (minute != lastHistoryMinute) {
            lastHistoryMinute = minute;
            Map<String, Object> h = new LinkedHashMap<>();
            h.put("ts", now);
            h.put("tps", round(tps[0]));
            h.put("mspt", s.get("mspt"));
            h.put("mem", used);
            history.addLast(h);
            while (history.size() > HISTORY_MINUTES) {
                history.removeFirst();
            }
        }
        s.put("history", new ArrayList<>(history));
        String json = gson.toJson(s);
        server.getScheduler().runTaskAsynchronously(this, () -> write(json));
    }

    private void write(String json) {
        synchronized (writeLock) {
            try {
                Files.createDirectories(out.getParent());
                Path tmp = out.resolveSibling(out.getFileName() + ".tmp");
                Files.writeString(tmp, json, StandardCharsets.UTF_8);
                Files.move(tmp, out, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
            } catch (IOException e) {
                getLogger().log(Level.WARNING, "Could not write " + out, e);
            }
        }
    }

    private static double round(double v) {
        return Math.round(v * 100.0) / 100.0;
    }
}
