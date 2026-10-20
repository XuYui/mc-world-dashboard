package io.github.xuyui.deathmarkers;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.reflect.TypeToken;
import java.awt.Color;
import java.awt.image.BufferedImage;
import java.io.IOException;
import java.io.Reader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.time.Instant;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
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
import org.bukkit.entity.Player;
import org.bukkit.event.EventHandler;
import org.bukkit.event.EventPriority;
import org.bukkit.event.Listener;
import org.bukkit.event.entity.PlayerDeathEvent;
import org.bukkit.plugin.java.JavaPlugin;
import xyz.jpenilla.squaremap.api.Key;
import xyz.jpenilla.squaremap.api.MapWorld;
import xyz.jpenilla.squaremap.api.Point;
import xyz.jpenilla.squaremap.api.SimpleLayerProvider;
import xyz.jpenilla.squaremap.api.Squaremap;
import xyz.jpenilla.squaremap.api.SquaremapProvider;
import xyz.jpenilla.squaremap.api.marker.Icon;
import xyz.jpenilla.squaremap.api.marker.Marker;
import xyz.jpenilla.squaremap.api.marker.MarkerOptions;

/**
 * Records every player death (time, position, message) to deaths.json and shows each one
 * as a gravestone on the squaremap web map.
 */
public final class DeathMarkersPlugin extends JavaPlugin implements Listener {
    private static final Key ICON = Key.of("deathmarkers_grave");
    private static final Key LAYER = Key.of("deathmarkers");
    private static final Pattern ARG = Pattern.compile("%(?:(\\d+)\\$)?s|%%");

    /** One recorded death. Field names are the JSON format read by the dashboard. */
    static final class Grave {
        long ts;          // epoch millis
        String uuid;
        String name;
        String world;     // dimension key, e.g. minecraft:the_nether
        double x;
        double y;
        double z;
        String message;   // death message, translated with lang.json when present
    }

    private final Gson gson = new GsonBuilder().setPrettyPrinting().disableHtmlEscaping().create();
    private final List<Grave> graves = new ArrayList<>();
    private final Map<String, SimpleLayerProvider> layers = new HashMap<>();
    private Map<String, String> lang = Map.of();
    private Path file;
    private DateTimeFormatter timeFormat;
    private int iconSize;

    @Override
    public void onEnable() {
        saveDefaultConfig();
        iconSize = getConfig().getInt("icon-size", 20);
        timeFormat = DateTimeFormatter.ofPattern(getConfig().getString("time-format", "yyyy-MM-dd HH:mm"))
            .withZone(ZoneId.systemDefault());
        file = getDataFolder().toPath().resolve("deaths.json");
        loadGraves();
        loadLang();

        Squaremap api = SquaremapProvider.get();
        api.iconRegistry().register(ICON, gravestone());
        for (MapWorld world : api.mapWorlds()) {
            SimpleLayerProvider layer = SimpleLayerProvider.builder(getConfig().getString("layer-label", "Deaths"))
                .showControls(true)
                .defaultHidden(getConfig().getBoolean("default-hidden", false))
                .layerPriority(5)
                .zIndex(5)
                .build();
            world.layerRegistry().register(LAYER, layer);
            layers.put(world.identifier().asString(), layer);
        }
        for (Grave g : graves) {
            addMarker(g);
        }
        getServer().getPluginManager().registerEvents(this, this);
        getLogger().info("Loaded " + graves.size() + " recorded deaths");
    }

    @Override
    public void onDisable() {
        try {
            Squaremap api = SquaremapProvider.get();
            for (MapWorld world : api.mapWorlds()) {
                if (world.layerRegistry().hasEntry(LAYER)) {
                    world.layerRegistry().unregister(LAYER);
                }
            }
            if (api.iconRegistry().hasEntry(ICON)) {
                api.iconRegistry().unregister(ICON);
            }
        } catch (IllegalStateException ignored) {
            // squaremap already shut down
        }
        layers.clear();
    }

    @EventHandler(priority = EventPriority.MONITOR, ignoreCancelled = true)
    public void onDeath(PlayerDeathEvent event) {
        Player player = event.getPlayer();
        Location at = player.getLocation();
        Component message = event.deathMessage();
        Grave g = new Grave();
        g.ts = System.currentTimeMillis();
        g.uuid = player.getUniqueId().toString();
        g.name = player.getName();
        g.world = at.getWorld().getKey().asString();
        g.x = at.getX();
        g.y = at.getY();
        g.z = at.getZ();
        g.message = message == null ? player.getName() : render(message);
        graves.add(g);
        addMarker(g);
        String json = gson.toJson(graves);
        getServer().getScheduler().runTaskAsynchronously(this, () -> save(json));
    }

    private void addMarker(Grave g) {
        SimpleLayerProvider layer = layers.get(g.world);
        if (layer == null) {
            return;  // world not shown on the map
        }
        String tooltip = "<b>" + html(g.name) + "</b><br>" + html(g.message) + "<br>"
            + html(timeFormat.format(Instant.ofEpochMilli(g.ts)))
            + String.format(Locale.ROOT, " · (%d, %d, %d)", Math.round(g.x), Math.round(g.y), Math.round(g.z));
        Icon icon = Marker.icon(Point.of(g.x, g.z), ICON, iconSize);
        icon.markerOptions(MarkerOptions.builder().hoverTooltip(tooltip).clickTooltip(tooltip));
        layer.addMarker(Key.of("grave_" + g.ts + "_" + g.uuid.replace("-", "")), icon);
    }

    // ---------- storage ----------

    private void loadGraves() {
        if (!Files.exists(file)) {
            return;
        }
        try (Reader r = Files.newBufferedReader(file, StandardCharsets.UTF_8)) {
            List<Grave> loaded = gson.fromJson(r, new TypeToken<List<Grave>>() { }.getType());
            if (loaded != null) {
                graves.addAll(loaded);
            }
        } catch (IOException | RuntimeException e) {
            getLogger().log(Level.SEVERE, "Could not read " + file + "; starting with no recorded deaths", e);
        }
    }

    private synchronized void save(String json) {
        try {
            Files.createDirectories(file.getParent());
            Path tmp = file.resolveSibling("deaths.json.tmp");
            Files.writeString(tmp, json, StandardCharsets.UTF_8);
            Files.move(tmp, file, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE);
        } catch (IOException e) {
            getLogger().log(Level.WARNING, "Could not save " + file, e);
        }
    }

    // ---------- death message text ----------

    /** Optional lang.json (e.g. zh_cn strings) next to config.yml; without it messages stay in English. */
    private void loadLang() {
        Path p = getDataFolder().toPath().resolve("lang.json");
        if (!Files.exists(p)) {
            return;
        }
        try (Reader r = Files.newBufferedReader(p, StandardCharsets.UTF_8)) {
            Map<String, String> loaded = gson.fromJson(r, new TypeToken<Map<String, String>>() { }.getType());
            if (loaded != null) {
                lang = loaded;
            }
        } catch (IOException | RuntimeException e) {
            getLogger().log(Level.WARNING, "Could not read " + p + "; death messages stay in English", e);
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

    private static String html(String s) {
        return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;");
    }

    // ---------- icon ----------

    /** A 16x16 pixel-art gravestone, drawn here so the plugin ships no game textures. */
    private static BufferedImage gravestone() {
        String[] rows = {
            "................",
            "................",
            ".....######.....",
            "....#hhhhss#....",
            "...#hhhhhsss#...",
            "...#hhh##sss#...",
            "...#hh####ss#...",
            "...#hhh##sss#...",
            "...#hhh##sss#...",
            "...#hhhhhsss#...",
            "...#hhhhhsss#...",
            "...#hhhhhsss#...",
            "..##########dd..",
            ".gggggggggggggg.",
            ".dddddddddddddd.",
            "................",
        };
        Map<Character, Color> palette = Map.of(
            '#', new Color(0x2b2b2b), 'h', new Color(0xa0a0a0), 's', new Color(0x6e6e6e),
            'g', new Color(0x5e9c3a), 'd', new Color(0x6b4a2b));
        BufferedImage img = new BufferedImage(32, 32, BufferedImage.TYPE_INT_ARGB);
        for (int y = 0; y < 16; y++) {
            for (int x = 0; x < 16; x++) {
                Color c = palette.get(rows[y].charAt(x));
                if (c != null) {
                    int argb = c.getRGB();
                    img.setRGB(x * 2, y * 2, argb);
                    img.setRGB(x * 2 + 1, y * 2, argb);
                    img.setRGB(x * 2, y * 2 + 1, argb);
                    img.setRGB(x * 2 + 1, y * 2 + 1, argb);
                }
            }
        }
        return img;
    }
}
