package io.github.xuyui.worlddashboard;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.reflect.TypeToken;
import java.io.BufferedWriter;
import java.io.IOException;
import java.io.Reader;
import java.lang.management.ManagementFactory;
import java.lang.reflect.Method;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.logging.Level;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import net.kyori.adventure.text.Component;
import net.kyori.adventure.text.TextComponent;
import net.kyori.adventure.text.TranslatableComponent;
import net.kyori.adventure.text.TranslationArgument;
import net.kyori.adventure.text.serializer.plain.PlainTextComponentSerializer;
import net.kyori.adventure.translation.GlobalTranslator;
import org.bukkit.Location;
import org.bukkit.Server;
import org.bukkit.World;
import org.bukkit.attribute.Attribute;
import org.bukkit.attribute.AttributeInstance;
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.entity.PlayerDeathEvent;
import org.bukkit.event.player.PlayerJoinEvent;
import org.bukkit.event.player.PlayerQuitEvent;
import org.bukkit.plugin.java.JavaPlugin;

/**
 * Feeds the world dashboard. Writes two files into its data folder:
 *
 * <ul>
 *   <li>{@code events.jsonl}: one JSON object per line for server start/stop, joins, quits and
 *       deaths (with position and death message), appended as they happen;</li>
 *   <li>{@code live.json}: every couple of seconds, who is online (position, health, hunger, ...)
 *       and the server's load (TPS, tick time, memory, CPU) with an hour of per-minute history.</li>
 * </ul>
 *
 * <p>When the dashboard changes someone's skin it drops {@code skin-apply/<uuid>} here; if that
 * player is online the plugin asks SkinsRestorer (optional, found by reflection) to re-apply it.
 *
 * <p>The dashboard backend reads both; the plugin itself serves nothing and needs no other plugin.
 * While the server is paused because nobody is online, ticks stop and so does live.json.
 */
public final class WorldDashboardPlugin extends JavaPlugin implements Listener {
    private static final Pattern ARG = Pattern.compile("%(?:(\\d+)\\$)?s|%%");
    private static final int HISTORY_MINUTES = 60;

    private final Gson gson = new GsonBuilder().disableHtmlEscaping().create();
    private final ExecutorService io = Executors.newSingleThreadExecutor(r -> {
        Thread t = new Thread(r, "WorldDashboard-io");
        t.setDaemon(true);
        return t;
    });
    private final ArrayDeque<Map<String, Object>> history = new ArrayDeque<>();
    private Map<String, String> lang = Map.of();
    private Path events;
    private Path live;
    private Path skinApply;
    private Object skinApplier;
    private Method applySkin;
    private long lastHistoryMinute = -1;

    @Override
    public void onEnable() {
        saveDefaultConfig();
        Path dir = getDataFolder().toPath();
        events = dir.resolve("events.jsonl");
        live = dir.resolve("live.json");
        skinApply = dir.resolve("skin-apply");
        loadLang(dir.resolve("lang.json"));
        getServer().getPluginManager().registerEvents(this, this);
        event("server_start", null, null);
        // Worlds are loaded by now; "ready" marks when players can join.
        getServer().getScheduler().runTask(this, () -> {
            event("server_ready", null, null);
            hookSkinsRestorer();
        });
        long period = Math.max(20L, getConfig().getLong("live-interval-seconds", 2) * 20L);
        getServer().getScheduler().runTaskTimer(this, this::writeLive, 20L, period);
    }

    @Override
    public void onDisable() {
        event("server_stop", null, null);
        Map<String, Object> s = new LinkedHashMap<>();
        s.put("ts", System.currentTimeMillis());
        s.put("level", level());
        s.put("stopped", true);
        s.put("players", List.of());
        String json = gson.toJson(s);
        io.submit(() -> writeAtomic(live, json));
        io.shutdown();
        try {
            io.awaitTermination(5, TimeUnit.SECONDS);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }

    // ---------- events ----------

    @EventHandler(priority = EventPriority.MONITOR)
    public void onJoin(PlayerJoinEvent e) {
        event("join", e.getPlayer(), null);
    }

    @EventHandler(priority = EventPriority.MONITOR)
    public void onQuit(PlayerQuitEvent e) {
        event("quit", e.getPlayer(), null);
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void onDeath(PlayerDeathEvent e) {
        Component message = e.deathMessage();
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("message", message == null ? e.getPlayer().getName() : render(message));
        event("death", e.getPlayer(), data);
    }

    private void event(String type, Player player, Map<String, Object> data) {
        Map<String, Object> e = new LinkedHashMap<>();
        e.put("ts", System.currentTimeMillis());
        e.put("type", type);
        e.put("level", level());
        if (player != null) {
            Location at = player.getLocation();
            e.put("name", player.getName());
            e.put("uuid", player.getUniqueId().toString());
            e.put("world", at.getWorld().getKey().asString());
            e.put("x", round(at.getX()));
            e.put("y", round(at.getY()));
            e.put("z", round(at.getZ()));
        }
        if (data != null) {
            e.put("data", data);
        }
        String line = gson.toJson(e) + "\n";
        io.submit(() -> append(line));
    }

    private String level() {
        List<World> worlds = getServer().getWorlds();
        return worlds.isEmpty() ? null : worlds.get(0).getName();
    }

    // ---------- live state ----------

    private void writeLive() {
        applyRequestedSkins();
        Server server = getServer();
        List<Map<String, Object>> players = new ArrayList<>();
        for (Player p : server.getOnlinePlayers()) {
            Location at = p.getLocation();
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("name", p.getName());
            m.put("uuid", p.getUniqueId().toString());
            m.put("world", at.getWorld().getKey().asString());
            m.put("x", round(at.getX()));
            m.put("y", round(at.getY()));
            m.put("z", round(at.getZ()));
            m.put("yaw", Math.round(at.getYaw()));
            m.put("health", round(p.getHealth()));
            m.put("food", p.getFoodLevel());
            AttributeInstance armor = p.getAttribute(Attribute.ARMOR);
            m.put("armor", armor == null ? 0 : (int) Math.round(armor.getValue()));
            m.put("level", p.getLevel());
            m.put("mode", p.getGameMode().name().toLowerCase(Locale.ROOT));
            players.add(m);
        }

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
        Map<String, Object> health = new LinkedHashMap<>();
        health.put("tps", new double[] {round(tps[0]), round(tps[1]), round(tps[2])});
        health.put("mspt", round(server.getAverageTickTime()));
        health.put("mem_used", used);
        health.put("mem_max", rt.maxMemory());
        health.put("cpu_process", round(processCpu * 100));
        health.put("cpu_system", round(systemCpu * 100));
        health.put("cores", rt.availableProcessors());
        health.put("chunks", chunks);
        health.put("entities", entities);
        long minute = now / 60000;
        if (minute != lastHistoryMinute) {
            lastHistoryMinute = minute;
            Map<String, Object> h = new LinkedHashMap<>();
            h.put("ts", now);
            h.put("tps", round(tps[0]));
            h.put("mspt", health.get("mspt"));
            h.put("mem", used);
            history.addLast(h);
            while (history.size() > HISTORY_MINUTES) {
                history.removeFirst();
            }
        }
        health.put("history", new ArrayList<>(history));

        Map<String, Object> s = new LinkedHashMap<>();
        s.put("ts", now);
        s.put("level", level());
        s.put("players", players);
        s.put("features", skinApplier != null ? List.of("skin-apply") : List.of());
        s.put("health", health);
        String json = gson.toJson(s);
        io.submit(() -> writeAtomic(live, json));
    }

    // ---------- skins (SkinsRestorer) ----------

    private void hookSkinsRestorer() {
        if (getServer().getPluginManager().getPlugin("SkinsRestorer") == null) {
            return;
        }
        try {
            Object api = Class.forName("net.skinsrestorer.api.SkinsRestorerProvider").getMethod("get").invoke(null);
            Class<?> sr = Class.forName("net.skinsrestorer.api.SkinsRestorer");
            Class<?> applier = Class.forName("net.skinsrestorer.api.SkinApplier");
            skinApplier = sr.getMethod("getSkinApplier", Class.class).invoke(api, Player.class);
            applySkin = applier.getMethod("applySkin", Object.class);
            getLogger().info("SkinsRestorer found: skins changed on the dashboard apply immediately");
        } catch (ReflectiveOperationException | LinkageError | RuntimeException ex) {
            getLogger().log(Level.WARNING, "SkinsRestorer is installed but its API could not be used", ex);
        }
    }

    /** Re-apply skins the dashboard changed; players who are offline get theirs on the next join anyway. */
    private void applyRequestedSkins() {
        if (!Files.isDirectory(skinApply)) {
            return;
        }
        try (var files = Files.list(skinApply)) {
            for (Path f : files.toList()) {
                Files.deleteIfExists(f);
                if (skinApplier == null) {
                    continue;
                }
                UUID id;
                try {
                    id = UUID.fromString(f.getFileName().toString());
                } catch (IllegalArgumentException ex) {
                    continue;
                }
                Player p = getServer().getPlayer(id);
                if (p != null) {
                    try {
                        applySkin.invoke(skinApplier, p);
                    } catch (ReflectiveOperationException | RuntimeException ex) {
                        getLogger().log(Level.WARNING, "Could not apply the new skin of " + p.getName(), ex);
                    }
                }
            }
        } catch (IOException ex) {
            getLogger().log(Level.WARNING, "Could not read " + skinApply, ex);
        }
    }

    // ---------- files (on the io thread) ----------

    private void append(String line) {
        try {
            Files.createDirectories(events.getParent());
            try (BufferedWriter w = Files.newBufferedWriter(events, StandardCharsets.UTF_8,
                    StandardOpenOption.CREATE, StandardOpenOption.APPEND)) {
                w.write(line);
            }
        } catch (IOException ex) {
            getLogger().log(Level.WARNING, "Could not append to " + events, ex);
        }
    }

    private void writeAtomic(Path target, String json) {
        try {
            Files.createDirectories(target.getParent());
            Path tmp = target.resolveSibling(target.getFileName() + ".tmp");
            Files.writeString(tmp, json, StandardCharsets.UTF_8);
            Files.move(tmp, target, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
        } catch (IOException ex) {
            getLogger().log(Level.WARNING, "Could not write " + target, ex);
        }
    }

    private static double round(double v) {
        return Math.round(v * 100.0) / 100.0;
    }

    // ---------- death message text ----------

    /** Optional lang.json (e.g. zh_cn strings) in the data folder; without it messages stay in English. */
    private void loadLang(Path p) {
        if (!Files.exists(p)) {
            return;
        }
        try (Reader r = Files.newBufferedReader(p, StandardCharsets.UTF_8)) {
            Map<String, String> loaded = gson.fromJson(r, new TypeToken<Map<String, String>>() { }.getType());
            if (loaded != null) {
                lang = loaded;
            }
        } catch (IOException | RuntimeException ex) {
            getLogger().log(Level.WARNING, "Could not read " + p + "; death messages stay in English", ex);
        }
    }

    private String render(Component c) {
        StringBuilder out = new StringBuilder();
        if (c instanceof TranslatableComponent t) {
            String template = lang.get(t.key());
            if (template == null) {
                Component english = GlobalTranslator.render(t.children(List.of()), Locale.US);
                out.append(PlainTextComponentSerializer.plainText().serialize(english));
            } else {
                List<String> args = new ArrayList<>();
                for (TranslationArgument a : t.arguments()) {
                    args.add(render(a.asComponent()));
                }
                out.append(format(template, args));
            }
        } else if (c instanceof TextComponent text) {
            out.append(text.content());
        } else {
            out.append(PlainTextComponentSerializer.plainText().serialize(c.children(List.of())));
        }
        for (Component child : c.children()) {
            out.append(render(child));
        }
        return out.toString();
    }

    private static String format(String template, List<String> args) {
        Matcher m = ARG.matcher(template);
        StringBuilder out = new StringBuilder();
        int next = 0;
        while (m.find()) {
            String rep;
            if (m.group().equals("%%")) {
                rep = "%";
            } else {
                int i = m.group(1) != null ? Integer.parseInt(m.group(1)) - 1 : next++;
                rep = i < args.size() ? args.get(i) : "";
            }
            m.appendReplacement(out, Matcher.quoteReplacement(rep));
        }
        m.appendTail(out);
        return out.toString();
    }
}
