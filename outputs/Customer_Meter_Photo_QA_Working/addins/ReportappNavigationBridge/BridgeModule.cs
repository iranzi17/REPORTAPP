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
        private readonly Dictionary<string, DateTime> _retry = new();
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
            if (_busy) return;
            _busy = true;
            try
            {
                // Process at most one per tick; do not monopolize map UI.
                var file = Directory.EnumerateFiles(_incoming, "*.json")
                                    .Where(f => !_retry.TryGetValue(f, out var until) || until <= DateTime.UtcNow)
                                    .OrderBy(File.GetCreationTimeUtc)
                                    .FirstOrDefault();
                if (file == null) return;
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
                    _retry.Remove(file);
                }
                else
                {
                    Log(Path.GetFileName(file) + ": " + issue);
                    _retry[file] = DateTime.UtcNow.AddMinutes(1);
                    // Don't delete the clicked request if the map isn't ready,
                    // the service is inaccessible or the feature is filtered.
                    // The request remains for another attempt.
                    var age = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()
                              - request!.CreatedUtcMs;
                    if (age > TimeSpan.FromHours(24).TotalMilliseconds)
                        Finish(file, ".expired", issue);
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
            if (age < -60000 || age > TimeSpan.FromHours(24).TotalMilliseconds)
                throw new InvalidDataException("Request outside allowed time window.");
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
                // Select only the requested record and zoom to selection.
                // MapView.ZoomTo(layer, objectid) is NOT an ArcGIS Pro 3.4
                // API overload; ZoomToSelected() is supported by SDK 3.4.
                using var selected = layer.Select(
                    filter, SelectionCombinationMethod.New);
                if (selected.GetCount() != 1)
                    return (string?)"OBJECTID not selectable (possibly filtered or deleted).";
                // ZoomToSelected considers every map selection. Clear unrelated
                // selections only after the requested record is confirmed.
                view.Map.ClearSelection();
                using var exactSelection = layer.Select(filter, SelectionCombinationMethod.New);
                layer.SetVisibility(true);
                return (string?)null;
            });
            if (issue != null) return issue;
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
                if (camera != null && !await view.ZoomToAsync(camera, TimeSpan.Zero))
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
