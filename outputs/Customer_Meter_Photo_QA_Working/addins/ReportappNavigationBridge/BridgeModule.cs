// REPORTAPP ArcGIS Pro SDK add-in module (ArcGIS Pro 3.3+ / .NET 8).
// Add to a matching ArcGIS Pro SDK Module Add-in project. See README.md.
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
using ArcGIS.Desktop.Framework.Contracts;
using ArcGIS.Desktop.Framework.Threading.Tasks;
using ArcGIS.Desktop.Mapping;

namespace ReportappNavigationBridge
{
    internal sealed class NavigationRequest
    {
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
        private readonly string _incoming = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "REPORTAPP", "Navigation", "Requests");

        protected override bool Initialize()
        {
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
                                    .OrderBy(File.GetCreationTimeUtc)
                                    .FirstOrDefault();
                if (file == null) return;
                NavigationRequest? request;
                try
                {
                    request = JsonSerializer.Deserialize<NavigationRequest>(
                        File.ReadAllText(file));
                    Validate(request);
                }
                catch (Exception ex)
                {
                    Finish(file, ".invalid", ex.Message);
                    return;
                }

                string? issue = await ZoomToFeatureAsync(request!);
                if (issue == null)
                {
                    File.Delete(file);
                }
                else
                {
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
            if (req == null || req.Version != 1
                || req.ObjectId <= 0
                || req.Origin != "REPORTAPP_NOTIFICATION"
                || !string.Equals(req.ServiceUrl.TrimEnd('/'), Service,
                                  StringComparison.OrdinalIgnoreCase)
                || (req.Asset, req.LayerId) switch
                {
                    ("pole",12) => false,
                    ("line",10) => false,
                    ("transformer",7) => false,
                    _ => true
                })
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
                string path = layer.GetPath()?.ToString() ?? "";
                // Do NOT match by display-name only: Electric Device, Electric
                // Line and Structure Junction can exist in other databases.
                return string.Equals(
                    path.TrimEnd('/'), exactUrl.TrimEnd('/'),
                    StringComparison.OrdinalIgnoreCase);
            }
            catch
            {
                return false;
            }
        }

        private static Task<string?> ZoomToFeatureAsync(NavigationRequest req)
        {
            return QueuedTask.Run(() =>
            {
                var view = MapView.Active;
                if (view == null || view.Map == null)
                    return (string?)"Open an ArcGIS Pro map before clicking the alert.";
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
                var filter = new QueryFilter
                {
                    ObjectIDs = new List<long> { req.ObjectId }
                };
                using var selected = layer.Select(
                    filter, SelectionCombinationMethod.New);
                if (selected.GetCount() != 1)
                    return (string?)"OBJECTID not selectable (possibly filtered or deleted).";
                view.ZoomTo(layer, req.ObjectId);
                return (string?)null;
            });
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
