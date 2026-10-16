// REPORTAPP ArcGIS Pro SDK add-in module (ArcGIS Pro 3.4 / .NET 8).
// Build with Build.ps1; pinned to the ArcGIS Pro 3.4 SDK.
// Reads ONLY the current Windows user's validated navigation request files.
// Never calls editing APIs or writes to the REG FeatureServer.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading.Tasks;
using System.Windows.Threading;
using ArcGIS.Core.Data;
using ArcGIS.Core.CIM;
using System.Data.Common;
using System.Threading;
using ArcGIS.Desktop.Framework.Contracts;
using ArcGIS.Desktop.Framework.Threading.Tasks;
using ArcGIS.Desktop.Mapping;

namespace ReportappNavigationBridge
{
    internal sealed class NavigationRequest
    {
        [JsonPropertyName("request_id")] public string RequestId { get; set; } = "";
        [JsonPropertyName("version")] public int Version { get; set; }
        [JsonPropertyName("asset")] public string Asset { get; set; } = "";
        [JsonPropertyName("objectid")] public long ObjectId { get; set; }
        [JsonPropertyName("layer_id")] public int LayerId { get; set; }
        [JsonPropertyName("service_url")] public string ServiceUrl { get; set; } = "";
        [JsonPropertyName("created_utc_ms")] public long CreatedUtcMs { get; set; }
        [JsonPropertyName("origin")] public string Origin { get; set; } = "";
    }

    internal class BridgeModule : Module
    {
        private const string Service =
            "https://gisweb.reg.rw/server/rest/services/REGUN_Service__Versio2/FeatureServer";
        private DispatcherTimer? _timer;
        private bool _busy;
        private Mutex? _owner;
        // Navigation is strictly one-shot: never silently retry a failed click.
        // A late retry can change the supervisor's active selection minutes later.
        private const long MaxNavigationAgeMs = 15000;
        private readonly string _pausedFlag = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "REPORTAPP", "Navigation", "navigation-paused.flag");
        private readonly string _incoming = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "REPORTAPP", "Navigation", "Requests");

        protected override bool Initialize()
        {
            // Only one Pro process consumes this user's queue. OS releases on crash.
            _owner = new Mutex(false, "Local\\REPORTAPP.Navigation.Bridge");
            bool acquired;
            try { acquired = _owner.WaitOne(0); }
            catch (AbandonedMutexException) { acquired = true; }
            if (!acquired) { _owner.Dispose(); _owner = null; return true; }
            Directory.CreateDirectory(_incoming);
            _timer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(2) };
            _timer.Tick += OnTick;
            _timer.Start();
            return base.Initialize();
        }

        protected override void Uninitialize()
        {
            if (_timer != null)
            {
                _timer.Stop();
                _timer.Tick -= OnTick;
                _timer = null;
            }
            _owner?.ReleaseMutex();
            _owner?.Dispose();
            base.Uninitialize();
        }

        private async void OnTick(object? sender, EventArgs args)
        {
            if (_busy || File.Exists(_pausedFlag)) return;
            _busy = true;
            try
            {
                // Process at most one per tick; do not monopolize map UI.
                var requests = Directory.EnumerateFiles(_incoming, "*.json")
                                        .OrderByDescending(File.GetCreationTimeUtc)
                                        .ToList();
                var file = requests.FirstOrDefault();
                if (file == null) return;
                // Latest explicit click wins. Earlier unprocessed requests
                // must never zoom the map later, even if their source exists.
                foreach (var previous in requests.Skip(1))
                    Finish(previous, ".superseded",
                           "Ignored older navigation click; newer request exists.");
                NavigationRequest? request;
                try
                {
                    request = JsonSerializer.Deserialize<NavigationRequest>(
                        (new FileInfo(file).Length <= 8192 ? File.ReadAllText(file) : throw new InvalidDataException("Oversized request")));
                    Validate(request);
                    if (Path.GetFileNameWithoutExtension(file) != request!.RequestId ||
                        File.Exists(file + ".done"))
                        throw new InvalidDataException("Duplicate or mismatched request identity.");
                }
                catch (Exception ex)
                {
                    Finish(file, ".invalid", ex.Message);
                    return;
                }

                string? issue;
                try { issue = await ZoomToFeatureAsync(request!); }
                catch (Exception ex) { issue = "REG navigation failed: " + ex.Message; }
                if (issue == null)
                {
                    ArcGIS.Desktop.Framework.FrameworkApplication.Current.MainWindow.Activate();
                    Finish(file, ".done", "Selected " + request!.Asset + " OBJECTID " + request.ObjectId);
                    // Success is terminal; no retry queue exists.
                }
                else
                {
                    // Failure is terminal. Never replay after the user has
                    // returned to a different map or engineering task.
                    Finish(file, ".failed", issue);
                }
            }
            catch (Exception ex)
            {
                Log(ex.ToString());
            }
            finally
            {
                _busy = false;
            }
        }

        private static void Validate(NavigationRequest? req)
        {
            if (req == null || !Guid.TryParseExact(req.RequestId, "N", out _) || req.Version != 1
                || req.ObjectId <= 0
                || req.Origin != "REPORTAPP_NOTIFICATION"
                || !string.Equals(req.ServiceUrl.TrimEnd('/'), Service,
                                  StringComparison.OrdinalIgnoreCase)
                || ((req.Asset, req.LayerId) switch
                {
                    ("pole",12) => false,
                    ("line",10) => false,
                    ("transformer",7) => false,
                    _ => true
                }))
            {
                throw new InvalidDataException("Invalid REPORTAPP zoom request.");
            }
            var age = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds() - req.CreatedUtcMs;
            if (age < -1000 || age > MaxNavigationAgeMs)
                throw new InvalidDataException(
                    "Navigation click expired after 15 seconds; use Zoom again.");
        }

        private static bool FreshAndCurrent(NavigationRequest request, MapView view)
        {
            var age = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()
                      - request.CreatedUtcMs;
            if (age < -1000 || age > MaxNavigationAgeMs ||
                !ReferenceEquals(MapView.Active, view) ||
                File.Exists(Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                    "REPORTAPP", "Navigation", "navigation-paused.flag")))
                return false;
            // If the supervisor clicked a newer item while a FeatureServer
            // query was running, discard this old navigation before selection.
            var requestedAt = request.CreatedUtcMs;
            return !Directory.EnumerateFiles(
                    Path.Combine(Environment.GetFolderPath(
                        Environment.SpecialFolder.LocalApplicationData),
                        "REPORTAPP", "Navigation", "Requests"), "*.json")
                .Where(file => Path.GetFileNameWithoutExtension(file) != request.RequestId)
                .Any(file => File.GetCreationTimeUtc(file).Ticks >
                             DateTimeOffset.FromUnixTimeMilliseconds(requestedAt).UtcDateTime.Ticks);
        }

        private static bool MatchesSource(FeatureLayer layer, string exactUrl)
        {
            try
            {
                // CIM connection verifies service, numeric dataset and version.
                if (layer.GetDataConnection() is not CIMStandardDataConnection dc)
                    return false;
                var connection = new DbConnectionStringBuilder { ConnectionString = dc.WorkspaceConnectionString };
                if (connection.TryGetValue("VERSION", out var version) &&
                    !string.Equals(Convert.ToString(version), "sde.DEFAULT", StringComparison.OrdinalIgnoreCase))
                    return false;
                if (!connection.TryGetValue("URL", out var source)) return false;
                var root = Convert.ToString(source)?.TrimEnd('/') ?? "";
                var candidate = root.EndsWith("/" + dc.Dataset, StringComparison.OrdinalIgnoreCase)
                    ? root : root + "/" + dc.Dataset;
                return string.Equals(candidate, exactUrl, StringComparison.OrdinalIgnoreCase);
            }
            catch
            {
                return false;
            }
        }

        private static async Task<string?> ZoomToFeatureAsync(NavigationRequest req)
        {
            var view = MapView.Active;
            if (view == null)
                return "Open an ArcGIS Pro map before clicking the alert.";
            var issue = await QueuedTask.Run(() =>
            {
                string url = Service + "/" +
                    req.LayerId.ToString(CultureInfo.InvariantCulture);
                var matches = view.Map.GetLayersAsFlattenedList()
                    .OfType<FeatureLayer>()
                    .Where(layer => MatchesSource(layer,url))
                    .ToList();
                if (matches.Count > 1)
                    return (string?)"Multiple source layers match; inspect the map.";
                FeatureLayer? layer = matches.FirstOrDefault();
                if (layer == null)
                {
                    // Add only the exact verified REG layer, not a similarly
                    // named layer from another Utility Network or geodatabase.
                    layer = LayerFactory.Instance.CreateLayer(
                        new Uri(url), view.Map) as FeatureLayer;
                    if (layer == null)
                        return (string?)"Unable to add REG source layer to the active map.";
                }
                using (var featureClass = layer.GetFeatureClass())
                using (var datastore = featureClass.GetDatastore())
                {
                    if (datastore is not Geodatabase database ||
                        database.GetConnector() is not ServiceConnectionProperties properties ||
                        !string.Equals(properties.URL.ToString().TrimEnd('/'), Service,
                                       StringComparison.OrdinalIgnoreCase))
                        return (string?)"Cannot verify the REG feature service connection.";
                    if (!string.IsNullOrEmpty(properties.Version) &&
                        !string.Equals(properties.Version, "sde.DEFAULT", StringComparison.OrdinalIgnoreCase))
                        return (string?)"Switch the REG layer to sde.DEFAULT and retry.";
                }
                var filter = new QueryFilter
                {
                    ObjectIDs = new List<long> { req.ObjectId }
                };
                // Read-only preflight: retries for missing records must NEVER
                // clear the surveyor's or supervisor's manual map selection.
                // FeatureLayer.Search respects the layer's definition query.
                using (var rows = layer.Search(filter))
                {
                    if (!rows.MoveNext())
                        return (string?)"OBJECTID not found in the current layer/version or excluded by a filter; manual selection preserved.";
                }
                if (!FreshAndCurrent(req,view))
                    return (string?)"A newer request or map activity superseded this click; manual selection preserved.";
                // Add first instead of New: if the feature stops being
                // selectable between Search and Select, existing selections
                // remain unchanged. GetObjectIDs may include earlier selections.
                using (var staged = layer.Select(filter, SelectionCombinationMethod.Add))
                {
                    if (!staged.GetObjectIDs().Contains(req.ObjectId))
                        return (string?)"OBJECTID not selectable in the current layer; manual selection preserved.";
                }
                // Once the target is verified selectable, select *only* this
                // record so ZoomToSelected does not zoom to unrelated features.
                // MapView.ZoomTo(layer, objectid) is not a Pro 3.4 overload.
                if (!FreshAndCurrent(req,view))
                    return (string?)"Click expired before selection; manual map extent preserved.";
                view.Map.ClearSelection();
                using (var exactSelection = layer.Select(filter, SelectionCombinationMethod.New))
                {
                    if (!exactSelection.GetObjectIDs().Contains(req.ObjectId))
                        return (string?)"OBJECTID became unavailable during final selection.";
                }
                layer.SetVisibility(true);
                return (string?)null;
            });
            if (issue != null) return issue;
            if (!FreshAndCurrent(req,view))
                return "Click expired or view changed before zoom; request discarded.";
            // Await navigation outside the MCT. Instant navigation avoids
            // animation interruption by map refreshes on the live REG map.
            if (!await view.ZoomToSelectedAsync(TimeSpan.Zero))
                return "ArcGIS Pro navigation was interrupted; request retained.";
            if (req.Asset != "line")
            {
                var camera = await QueuedTask.Run(() =>
                {
                    if (view.Map.MapType != MapType.Map) return null;
                    var camera = view.Camera;
                    camera.Scale = 1500;
                    return camera;
                });
                if (camera != null && FreshAndCurrent(req,view) &&
                    !await view.ZoomToAsync(camera, TimeSpan.Zero))
                    return "ArcGIS Pro inspection-scale navigation was interrupted.";
            }
            return null;
        }

        private void Finish(string source, string suffix, string explanation)
        {
            try
            {
                File.Move(source,source+suffix,true);
                Log(Path.GetFileName(source)+": "+explanation);
            }
            catch (Exception ex) { Log(ex.ToString()); }
        }

        private void Log(string note)
        {
            try
            {
                var file=Path.Combine(Path.GetDirectoryName(_incoming)!,
                                      "bridge-errors.log");
                File.AppendAllText(file,
                    DateTimeOffset.Now.ToString("O")+" "+note+Environment.NewLine);
            }
            catch { }
        }
    }
}
