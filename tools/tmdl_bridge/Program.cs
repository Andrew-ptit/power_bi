using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Microsoft.AnalysisServices.Tabular;

const int UsageError = 2;
const int InvalidTmdl = 10;

if (args.Length != 2 || args[0] != "catalog")
{
    Console.Error.WriteLine("USAGE_ERROR");
    return UsageError;
}

var source = Path.GetFullPath(args[1]);
if (!Directory.Exists(source))
{
    Console.Error.WriteLine("SOURCE_NOT_FOUND");
    return UsageError;
}

try
{
    var sourceHashBefore = FolderHash(source);
    var database = TmdlSerializer.DeserializeDatabaseFromFolder(source);
    var payload = Catalog(database, sourceHashBefore);
    if (FolderHash(source) != sourceHashBefore)
    {
        Console.Error.WriteLine("SOURCE_CHANGED");
        return 12;
    }
    Console.WriteLine(System.Text.Json.JsonSerializer.Serialize(payload));
    return 0;
}
catch (Exception exception)
{
    // Parser/model validation failures are intentionally collapsed to one safe
    // status. Never echo exception text: TMDL can contain paths or credentials.
    Console.Error.WriteLine($"INVALID_TMDL:{exception.GetType().Name}");
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
                .Select(column => new SortedDictionary<string, object?>
                {
                    ["name"] = column.Name,
                    ["description"] = column.Description,
                    ["dataType"] = column.DataType.ToString(),
                    ["sourceColumn"] = column is DataColumn dataColumn ? dataColumn.SourceColumn : null,
                    ["formatString"] = column.FormatString,
                    ["summarizeBy"] = column.SummarizeBy.ToString(),
                }).ToArray(),
            ["measures"] = table.Measures.OrderBy(measure => measure.Name, StringComparer.Ordinal)
                .Select(measure => new SortedDictionary<string, object?>
                {
                    ["name"] = measure.Name,
                    ["description"] = measure.Description,
                    ["expression"] = measure.Expression,
                    ["formatString"] = measure.FormatString,
                }).ToArray(),
            ["partitions"] = table.Partitions.OrderBy(partition => partition.Name, StringComparer.Ordinal)
                .Select(PartitionCatalog).ToArray(),
        }).ToArray();

    var relationships = database.Model.Relationships
        .OfType<SingleColumnRelationship>()
        .OrderBy(relationship => relationship.Name, StringComparer.Ordinal)
        .Select(relationship => new SortedDictionary<string, object?>
        {
            ["name"] = relationship.Name,
            ["fromTable"] = relationship.FromTable.Name,
            ["fromColumn"] = relationship.FromColumn.Name,
            ["fromCardinality"] = relationship.FromCardinality.ToString(),
            ["toTable"] = relationship.ToTable.Name,
            ["toColumn"] = relationship.ToColumn.Name,
            ["toCardinality"] = relationship.ToCardinality.ToString(),
            ["crossFilteringBehavior"] = relationship.CrossFilteringBehavior.ToString(),
            ["isActive"] = relationship.IsActive,
        }).ToArray();

    return new SortedDictionary<string, object?>
    {
        ["database"] = database.Name,
        ["compatibilityLevel"] = database.CompatibilityLevel,
        ["model"] = database.Model.Name,
        ["culture"] = database.Model.Culture,
        ["sourceHash"] = sourceHash,
        ["tableCount"] = tables.Length,
        ["relationshipCount"] = relationships.Length,
        ["relationships"] = relationships,
        ["tables"] = tables,
    };
}

static SortedDictionary<string, object?> PartitionCatalog(Partition partition)
{
    var result = new SortedDictionary<string, object?>
    {
        ["name"] = partition.Name,
        ["mode"] = partition.Mode.ToString(),
        ["sourceType"] = partition.SourceType.ToString(),
        ["expression"] = null,
    };
    if (partition.Source is MPartitionSource mSource)
    {
        result["expression"] = mSource.Expression;
    }
    return result;
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
