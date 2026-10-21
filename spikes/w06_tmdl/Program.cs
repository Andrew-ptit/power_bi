using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.AnalysisServices.Tabular;

const int UsageError = 2;
const int InvalidTmdl = 10;
const int UnsafeOutput = 11;

if (args.Length is < 2 or > 3 || args[0] is not ("inspect" or "roundtrip"))
{
    Console.Error.WriteLine("usage: TmdlSpike inspect <tmdl-folder> | roundtrip <tmdl-folder> <new-output-folder>");
    return UsageError;
}

var command = args[0];
var source = Path.GetFullPath(args[1]);
if (!Directory.Exists(source))
{
    Console.Error.WriteLine("SOURCE_NOT_FOUND: expected a TMDL folder");
    return UsageError;
}

try
{
    var sourceHashBefore = FolderHash(source);
    var database = TmdlSerializer.DeserializeDatabaseFromFolder(source);
    var catalog = Catalog(database, sourceHashBefore);

    if (command == "roundtrip")
    {
        if (args.Length != 3)
        {
            Console.Error.WriteLine("usage: TmdlSpike roundtrip <tmdl-folder> <new-output-folder>");
            return UsageError;
        }

        var output = Path.GetFullPath(args[2]);
        if (Directory.Exists(output) || File.Exists(output))
        {
            Console.Error.WriteLine("OUTPUT_EXISTS: roundtrip destination must not exist");
            return UnsafeOutput;
        }

        Directory.CreateDirectory(output);
        TmdlSerializer.SerializeDatabaseToFolder(database, output);
        if (FolderHash(source) != sourceHashBefore)
        {
            Console.Error.WriteLine("SOURCE_CHANGED: serializer operation modified the input folder");
            return UnsafeOutput;
        }

        catalog["outputHash"] = FolderHash(output);
    }

    Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(catalog, new JsonSerializerOptions { WriteIndented = true }));
    return 0;
}
catch (Exception exception) when (exception.GetType().FullName?.Contains("Tmdl", StringComparison.Ordinal) == true)
{
    Console.Error.WriteLine($"INVALID_TMDL: {exception.Message}");
    return InvalidTmdl;
}

static SortedDictionary<string, object?> Catalog(Database database, string sourceHash)
{
    var tables = database.Model.Tables
        .OrderBy(table => table.Name, StringComparer.Ordinal)
        .Select(table => new SortedDictionary<string, object?>
        {
            ["name"] = table.Name,
            ["description"] = table.Description,
            ["columns"] = table.Columns.OrderBy(column => column.Name, StringComparer.Ordinal)
                .Select(column => column.Name).ToArray(),
            ["measures"] = table.Measures.OrderBy(measure => measure.Name, StringComparer.Ordinal)
                .Select(measure => new SortedDictionary<string, object?>
                {
                    ["name"] = measure.Name,
                    ["description"] = measure.Description,
                    ["expression"] = measure.Expression,
                    ["formatString"] = measure.FormatString,
                }).ToArray(),
            ["partitions"] = table.Partitions.OrderBy(partition => partition.Name, StringComparer.Ordinal)
                .Select(partition => partition.Name).ToArray(),
        }).ToArray();

    var relationships = database.Model.Relationships
        .OfType<SingleColumnRelationship>()
        .OrderBy(relationship => relationship.Name, StringComparer.Ordinal)
        .Select(relationship => $"{relationship.FromTable.Name}.{relationship.FromColumn.Name}->{relationship.ToTable.Name}.{relationship.ToColumn.Name}")
        .ToArray();

    return new SortedDictionary<string, object?>
    {
        ["database"] = database.Name,
        ["sourceHash"] = sourceHash,
        ["tableCount"] = tables.Length,
        ["relationshipCount"] = relationships.Length,
        ["relationships"] = relationships,
        ["tables"] = tables,
    };
}

static string FolderHash(string root)
{
    using var aggregate = IncrementalHash.CreateHash(HashAlgorithmName.SHA256);
    foreach (var file in Directory.EnumerateFiles(root, "*", SearchOption.AllDirectories).OrderBy(path => path, StringComparer.Ordinal))
    {
        var relative = Path.GetRelativePath(root, file).Replace('\\', '/');
        aggregate.AppendData(Encoding.UTF8.GetBytes(relative));
        aggregate.AppendData(new byte[] { 0 });
        using var stream = File.OpenRead(file);
        var buffer = new byte[1024 * 1024];
        int read;
        while ((read = stream.Read(buffer, 0, buffer.Length)) > 0)
        {
            aggregate.AppendData(buffer, 0, read);
        }
        aggregate.AppendData(new byte[] { 0 });
    }
    return Convert.ToHexString(aggregate.GetHashAndReset()).ToLowerInvariant();
}
