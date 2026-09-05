namespace HermesFinance.Launcher;

/// <summary>
/// First-time setup dialog: the owner picks the prepared Stable/Preview
/// checkout and data directories explicitly. The dialog validates boundaries
/// via <see cref="LauncherSetup"/> and writes config.json only on success.
/// Plain functional layout — no visual design work belongs here (#284).
/// </summary>
public sealed class SetupForm : Form
{
    private readonly string _configPath;
    private readonly TextBox _stableCheckout = new() { Dock = DockStyle.Fill, ReadOnly = true };
    private readonly TextBox _stableData = new() { Dock = DockStyle.Fill, ReadOnly = true };
    private readonly TextBox _previewCheckout = new() { Dock = DockStyle.Fill, ReadOnly = true };
    private readonly TextBox _previewData = new() { Dock = DockStyle.Fill, ReadOnly = true };
    private readonly Label _status = new()
    {
        Dock = DockStyle.Fill,
        AutoSize = false,
        Height = 48,
    };
    private readonly Button _save = new() { Text = "Сохранить конфигурацию", Width = 200, Height = 36, DialogResult = DialogResult.None };
    private readonly Button _cancel = new() { Text = "Отмена", Width = 100, Height = 36, DialogResult = DialogResult.Cancel };

    public SetupForm(string configPath)
    {
        _configPath = configPath;
        Text = "Hermes Finance — первая настройка";
        StartPosition = FormStartPosition.CenterParent;
        MinimumSize = new Size(620, 380);
        ClientSize = new Size(620, 380);
        AcceptButton = _save;
        CancelButton = _cancel;
        BuildLayout();
    }

    private void BuildLayout()
    {
        var root = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 4,
            Padding = new Padding(16),
        };
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 60));
        root.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 56));
        root.RowStyles.Add(new RowStyle(SizeType.Absolute, 48));

        var intro = new Label
        {
            Text = "Выберите подготовленные каталоги. Stable — pinned release v0.8.2 и production-данные; Preview — изолированные данные, никогда не production. Ручной JSON не нужен.",
            Dock = DockStyle.Fill,
            AutoSize = false,
        };
        root.Controls.Add(intro, 0, 0);

        var grid = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 3,
            RowCount = 4,
        };
        grid.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 150));
        grid.ColumnStyles.Add(new ColumnStyle(SizeType.Percent, 100));
        grid.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute, 100));
        AddRow(grid, 0, "Stable checkout:", _stableCheckout);
        AddRow(grid, 1, "Stable данные:", _stableData);
        AddRow(grid, 2, "Preview checkout:", _previewCheckout);
        AddRow(grid, 3, "Preview данные:", _previewData);
        root.Controls.Add(grid, 0, 1);

        root.Controls.Add(_status, 0, 2);

        var actions = new FlowLayoutPanel
        {
            Dock = DockStyle.Fill,
            FlowDirection = FlowDirection.RightToLeft,
        };
        _save.Click += (_, _) => Save();
        actions.Controls.Add(_cancel);
        actions.Controls.Add(_save);
        root.Controls.Add(actions, 0, 3);

        Controls.Add(root);
    }

    private void AddRow(TableLayoutPanel grid, int row, string caption, TextBox target)
    {
        var label = new Label { Text = caption, Dock = DockStyle.Fill, TextAlign = ContentAlignment.MiddleLeft };
        var browse = new Button { Text = "Обзор…", Dock = DockStyle.Fill };
        browse.Click += (_, _) => Browse(target);
        grid.Controls.Add(label, 0, row);
        grid.Controls.Add(target, 1, row);
        grid.Controls.Add(browse, 2, row);
    }

    private void Browse(TextBox target)
    {
        using var dialog = new FolderBrowserDialog
        {
            Description = "Выберите подготовленный каталог",
            UseDescriptionForTitle = true,
            ShowNewFolderButton = false,
        };
        if (dialog.ShowDialog(this) == DialogResult.OK)
        {
            target.Text = dialog.SelectedPath;
        }
    }

    private void Save()
    {
        try
        {
            var config = LauncherSetup.BuildConfig(
                _stableCheckout.Text.Trim(),
                _stableData.Text.Trim(),
                _previewCheckout.Text.Trim(),
                _previewData.Text.Trim());
            LauncherSetup.WriteConfig(config, _configPath);
            DialogResult = DialogResult.OK;
            Close();
        }
        catch (Exception exception) when (exception is LauncherValidationException or IOException or UnauthorizedAccessException)
        {
            _status.Text = LauncherUi.OwnerFacingFailure(exception.Message);
        }
    }
}
