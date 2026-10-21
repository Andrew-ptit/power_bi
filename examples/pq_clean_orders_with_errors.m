let
    Source = Excel.CurrentWorkbook(){[Name="PQ_Input"]}[Content],
    IsBlank = (value as any) as logical =>
        let
            Check = try (
                if value = null then true
                else if Value.Is(value, type text) then Text.Trim(value) = ""
                else false
            )
        in
            if Check[HasError] then false else Check[Value],
    NonEmptyRows = Table.SelectRows(Source, (row) =>
        let
            Checks = List.Transform(Record.FieldNames(row), (field) =>
                let Cell = try Record.Field(row, field)
                in if Cell[HasError] then false else IsBlank(Cell[Value])
            )
        in
            not List.AllTrue(Checks)
    ),
    ValidOrderRows = Table.SelectRows(NonEmptyRows, each
        let
            OrderId = try [Ma_Don_Hang]
        in
            if OrderId[HasError] then true
            else if IsBlank(OrderId[Value]) then false
            else if Value.Is(OrderId[Value], type text)
                then Text.Lower(Text.Trim(OrderId[Value])) <> "null"
            else true
    ),
    // Keep rows Power Query sees as errors; comparing them during Table.Distinct can abort refresh.
    // Excel.CurrentWorkbook may expose worksheet error cells as null; original error codes are not guaranteed here.
    WithIndex = Table.AddIndexColumn(ValidOrderRows, "__PQ_RowIndex", 0, 1, Int64.Type),
    CompareColumns = Table.ColumnNames(ValidOrderRows),
    ErrorRows = Table.SelectRowsWithErrors(WithIndex, CompareColumns),
    CleanRows = Table.RemoveRowsWithErrors(WithIndex, CompareColumns),
    UniqueCleanRows = Table.Distinct(CleanRows, CompareColumns),
    Combined = Table.Combine({UniqueCleanRows, ErrorRows}),
    Ordered = Table.Sort(Combined, {{"__PQ_RowIndex", Order.Ascending}}),
    Result = Table.RemoveColumns(Ordered, {"__PQ_RowIndex"})
in
    Result
