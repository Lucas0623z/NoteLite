/* Copyright © NoteLite 2026. Licensed under the GNU Affero General Public License. */
package com.notelite.omr.practice;

import com.notelite.omr.score.LogicalPart;
import com.notelite.omr.score.Score;
import com.notelite.omr.score.StaffConfig;
import org.junit.After;
import org.junit.Test;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.Socket;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;

import static org.junit.Assert.*;

/** Real loopback HTTP requests exercise score privacy and service lifecycle. */
public class PracticeStudioTest
{
    @After public void stopStudio () { PracticeStudio.stop(); }

    @Test public void servesBundledAssetsAndAnImmutableScoreSnapshot () throws Exception {
        byte[] original = "<score-partwise>练习</score-partwise>".getBytes(StandardCharsets.UTF_8);
        URI uri = PracticeStudio.start(original);
        original[0] = '!';
        assertEquals("127.0.0.1", uri.getHost());
        try (HttpClient client = HttpClient.newHttpClient()) {
            var score = get(client, uri.resolve("score.musicxml"));
            assertEquals(200, score.statusCode());
            assertEquals("<score-partwise>练习</score-partwise>", score.body());
            assertEquals("no-store", score.headers().firstValue("Cache-Control").orElse(""));
            assertFalse(score.headers().firstValue("Access-Control-Allow-Origin").isPresent());
            assertTrue(score.headers().firstValue("Content-Security-Policy").orElse("").contains("connect-src 'self'"));
            assertTrue(get(client, uri).body().toLowerCase(java.util.Locale.ROOT).contains("<!doctype html>"));
            assertEquals(200, get(client, uri.resolve("app.js")).statusCode());
            assertEquals(200, get(client, uri.resolve("style.css")).statusCode());
            assertEquals(200, get(client, uri.resolve("demo.musicxml")).statusCode());
            var icon = get(client, uri.resolve("icons/play.svg"));
            assertEquals(200, icon.statusCode());
            assertEquals("image/svg+xml", icon.headers().firstValue("Content-Type").orElse(""));
            assertTrue(icon.body().contains("<svg"));
        }
    }

    @Test public void rejectsUnknownSessionsMethodsAndTraversal () throws Exception {
        URI uri = PracticeStudio.start("<score/>".getBytes(StandardCharsets.UTF_8));
        try (HttpClient client = HttpClient.newHttpClient()) {
            assertEquals(404, get(client, uri.resolve("/score.musicxml")).statusCode());
            assertEquals(404, get(client, URI.create(uri + "../score.musicxml")).statusCode());
            assertEquals(404, get(client, URI.create(uri + "%2e%2e%2fscore.musicxml")).statusCode());
            assertEquals(404, get(client, uri.resolve("missing.txt")).statusCode());
            assertEquals(404, get(client, URI.create(uri + "icons/%2e%2e%2fscore.musicxml")).statusCode());
            var post = HttpRequest.newBuilder(uri.resolve("score.musicxml")).POST(HttpRequest.BodyPublishers.ofString("mutate")).build();
            assertEquals(405, client.send(post, HttpResponse.BodyHandlers.ofString()).statusCode());
            assertEquals("<score/>", get(client, uri.resolve("score.musicxml")).body());
        }
    }

    @Test public void rejectsUnexpectedHostHeader () throws Exception {
        URI uri = PracticeStudio.start(new byte[0]);
        try (Socket socket = new Socket("127.0.0.1", uri.getPort())) {
            socket.setSoTimeout(3000);
            socket.getOutputStream().write(("GET " + uri.getPath() + "score.musicxml HTTP/1.1\r\n"
                    + "Host: example.com\r\nConnection: close\r\n\r\n").getBytes(StandardCharsets.US_ASCII));
            BufferedReader reader = new BufferedReader(new InputStreamReader(socket.getInputStream(), StandardCharsets.US_ASCII));
            assertTrue(reader.readLine().contains("403"));
        }
    }

    @Test public void replacementInvalidatesOldSessionAndStopClosesPort () throws Exception {
        URI first = PracticeStudio.start("first".getBytes(StandardCharsets.UTF_8));
        URI second = PracticeStudio.start("second".getBytes(StandardCharsets.UTF_8));
        assertNotEquals(first.getPath(), second.getPath());
        try (HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build()) {
            assertEquals("second", get(client, second.resolve("score.musicxml")).body());
            assertEquals(404, get(client, second.resolve(first.getPath() + "score.musicxml")).statusCode());
            PracticeStudio.stop();
            assertThrows(java.io.IOException.class, () -> get(client, second.resolve("score.musicxml")));
        }
    }

    @Test public void localEngineRoutesRequireExplicitSameOriginRequests () throws Exception {
        URI uri = PracticeStudio.start("<score/>".getBytes(StandardCharsets.UTF_8));
        try (HttpClient client = HttpClient.newHttpClient()) {
            assertEquals(200, get(client, uri.resolve("engines.json")).statusCode());
            assertEquals("{}", get(client, uri.resolve("score-info.json")).body());
            for (String route : new String[]{"audio/start", "audio/stop", "audio/discard", "analysis"}) {
                var missingOrigin = HttpRequest.newBuilder(uri.resolve(route)).POST(HttpRequest.BodyPublishers.noBody()).build();
                assertEquals(403, client.send(missingOrigin, HttpResponse.BodyHandlers.ofString()).statusCode());
                var external = HttpRequest.newBuilder(uri.resolve(route)).header("Origin", "https://example.com").POST(HttpRequest.BodyPublishers.noBody()).build();
                assertEquals(403, client.send(external, HttpResponse.BodyHandlers.ofString()).statusCode());
            }
            String origin = "http://127.0.0.1:" + uri.getPort();
            var badConfig = HttpRequest.newBuilder(uri.resolve("audio/start?min=1&max=5000&window=8192"))
                    .header("Origin", origin).POST(HttpRequest.BodyPublishers.noBody()).build();
            assertEquals(400, client.send(badConfig, HttpResponse.BodyHandlers.ofString()).statusCode());
            var simpleForm = HttpRequest.newBuilder(uri.resolve("analysis")).header("Origin", origin)
                    .header("Content-Type", "application/x-www-form-urlencoded").POST(HttpRequest.BodyPublishers.ofString("bad")).build();
            assertEquals(415, client.send(simpleForm, HttpResponse.BodyHandlers.ofString()).statusCode());
        }
    }

    @Test public void unnamedOmrPartsDoNotConfirmPlaybackDefaultsAsInstruments () {
        LogicalPart unnamed = new LogicalPart(1, 2, List.of(new StaffConfig(5, false), new StaffConfig(5, false)));
        Score score = new Score();
        score.setLogicalParts(List.of(unnamed));
        assertNull(unnamed.getName());
        assertNull(unnamed.getMidiProgram());
        assertEquals("Piano", unnamed.getDefaultName());
        assertEquals(Integer.valueOf(1), unnamed.getDefaultProgram());

        String metadata = PracticeStudio.instrumentMetadata(score);
        assertTrue(metadata.contains("\"origin\":\"local-omr\""));
        assertTrue(metadata.contains("\"id\":\"P1\""));
        assertTrue(metadata.contains("\"name\":\"\""));
        assertTrue(metadata.contains("\"program\":0"));
        assertTrue(metadata.contains("\"confirmed\":false"));
        assertFalse(metadata.contains("Piano"));
        // A playback program alone can also be a heuristic; a score label is
        // still required before an unnamed local OMR part is auto-confirmed.
        unnamed.setMidiProgram(1);
        String playbackOnly = PracticeStudio.instrumentMetadata(score);
        assertTrue(playbackOnly.contains("\"program\":1"));
        assertTrue(playbackOnly.contains("\"confirmed\":false"));
        assertNull(unnamed.getName());
    }

    @Test public void actualOmrNamesAndAbbreviationsRemainAvailableForInstrumentConfirmation () {
        LogicalPart named = new LogicalPart(1, 1, List.of(new StaffConfig(5, false)));
        named.setName("Clarinet");
        LogicalPart abbreviated = new LogicalPart(2, 1, List.of(new StaffConfig(5, false)));
        abbreviated.setAbbreviation("Vln.");
        Score score = new Score();
        score.setLogicalParts(List.of(named, abbreviated));
        String metadata = PracticeStudio.instrumentMetadata(score);
        assertTrue(metadata.contains("\"id\":\"P1\",\"name\":\"Clarinet\",\"abbreviation\":\"\",\"program\":0,\"confirmed\":true"));
        assertTrue(metadata.contains("\"id\":\"P2\",\"name\":\"\",\"abbreviation\":\"Vln.\",\"program\":0,\"confirmed\":true"));
        assertNull(named.getMidiProgram());
        assertNull(abbreviated.getName());
    }

    private static HttpResponse<String> get (HttpClient client, URI uri) throws Exception {
        return client.send(HttpRequest.newBuilder(uri).timeout(Duration.ofSeconds(5)).GET().build(),
                HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
    }
}
