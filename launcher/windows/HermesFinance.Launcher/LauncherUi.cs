using System.Drawing.Drawing2D;

namespace HermesFinance.Launcher;

internal enum LauncherReadinessState
{
    NotChecked,
    Checking,
    Ready,
    NeedsPreparation,
    Blocked,
    Starting,
    Running,
    Stopped,
}

internal static class LauncherUi
{
    public static string TypeBadge(string type) => type.ToLowerInvariant() switch
    {
        "stable" => "STABLE  ·  PRODUCTION",
        "preview" => "PREVIEW  ·  ISOLATED",
        "experiment" => "EXPERIMENT  ·  SANDBOX",
        _ => "PROFILE",
    };

    public static string DataBoundary(string type) => type.ToLowerInvariant() switch
    {
        "stable" => "Canonical production data",
        "preview" => "Isolated UAT / synthetic data",
        "experiment" => "Sandbox data only",
        _ => "Configured profile data",
    };

    public static string CardDescription(string type) => type.ToLowerInvariant() switch
    {
        "stable" => "Prepared production runtime",
        "preview" => "Prepared independent runtime",
        "experiment" => "Prepared sandbox runtime",
        _ => "Prepared Hermes Finance runtime",
    };

    public static string ReleaseBadge(string expectedRef)
    {
        if (string.IsNullOrWhiteSpace(expectedRef))
        {
            return "Prepared release";
        }

        var value = expectedRef.Trim();
        foreach (var prefix in new[] { "refs/tags/", "refs/heads/", "origin/" })
        {
            if (value.StartsWith(prefix, StringComparison.OrdinalIgnoreCase))
            {
                value = value[prefix.Length..];
                break;
            }
        }

        if (value.Length is > 0 and <= 24
            && !value.Any(char.IsWhiteSpace)
            && !value.Contains('\\')
            && !value.Contains('/'))
        {
            return $"Release {value}";
        }
        return "Prepared release";
    }

    public static string ReadinessLabel(LauncherReadinessState state) => state switch
    {
        LauncherReadinessState.NotChecked => "НЕ ПРОВЕРЕНО",
        LauncherReadinessState.Checking => "ПРОВЕРЯЕМ",
        LauncherReadinessState.Ready => "ГОТОВО",
        LauncherReadinessState.NeedsPreparation => "НУЖНА ПОДГОТОВКА",
        LauncherReadinessState.Blocked => "ЗАБЛОКИРОВАНО",
        LauncherReadinessState.Starting => "ЗАПУСКАЕМ",
        LauncherReadinessState.Running => "ЗАПУЩЕНО",
        LauncherReadinessState.Stopped => "ОСТАНОВЛЕНО",
        _ => "НЕ ПРОВЕРЕНО",
    };

    public static string ReadinessTitle(LauncherReadinessState state) => state switch
    {
        LauncherReadinessState.NotChecked => "Проверка ещё не запускалась",
        LauncherReadinessState.Checking => "Проверяем подготовленную среду…",
        LauncherReadinessState.Ready => "Готово к запуску",
        LauncherReadinessState.NeedsPreparation => "Нужна подготовка зависимостей",
        LauncherReadinessState.Blocked => "Запуск заблокирован",
        LauncherReadinessState.Starting => "Hermes запускается",
        LauncherReadinessState.Running => "Hermes работает",
        LauncherReadinessState.Stopped => "Hermes остановлен",
        _ => "Проверка ещё не запускалась",
    };

    public static string ReadinessDescription(LauncherReadinessState state) => state switch
    {
        LauncherReadinessState.NotChecked => "Выберите профиль, чтобы проверить его готовность.",
        LauncherReadinessState.Checking => "Проверяем identity, данные, зависимости и loopback-порт.",
        LauncherReadinessState.Ready => "Все preflight-проверки пройдены. Можно запускать Hermes.",
        LauncherReadinessState.NeedsPreparation => "При запуске launcher подготовит только locked-зависимости этого профиля.",
        LauncherReadinessState.Blocked => "Исправьте blocker в подготовленном runtime и повторите проверку.",
        LauncherReadinessState.Starting => "Ждём штатные health probes существующего guarded startup.",
        LauncherReadinessState.Running => "Сервис доступен только локально на 127.0.0.1:8000.",
        LauncherReadinessState.Stopped => "Профиль остановлен. Можно снова выполнить preflight.",
        _ => "Выберите профиль, чтобы проверить его готовность.",
    };

    public static string OwnerFacingFailure(string rawMessage)
    {
        var message = rawMessage.ToLowerInvariant();
        if (message.Contains("only one production profile") || message.Contains("exactly one stable"))
        {
            return "Конфигурация должна содержать ровно один Stable-профиль.";
        }
        if (message.Contains("launcher config") || message.Contains("config is invalid"))
        {
            return "Конфигурация launcher невалидна. Проверьте подготовленные профили.";
        }
        if (message.Contains("stable may use only the production runtime"))
        {
            return "Stable должен указывать только на canonical production runtime.";
        }
        if (message.Contains("stable may use only the production database"))
        {
            return "Stable должен использовать только canonical production database.";
        }
        if (message.Contains("cannot open production data") || message.Contains("aliases production"))
        {
            return "Preview и Experiment должны использовать собственные данные, не production.";
        }
        if (message.Contains("linked worktrees") || message.Contains("not independent"))
        {
            return "Профиль должен быть независимым checkout, а не linked worktree.";
        }
        if (message.Contains("identity does not match") || message.Contains("identity is ambiguous"))
        {
            return "Code identity профиля не совпадает с подготовленной версией или checkout изменён.";
        }
        if (message.Contains("sidecar") || message.Contains("unstamped data"))
        {
            return "Identity данных не подтверждён. Нужен корректный sidecar для этого профиля.";
        }
        if (message.Contains("schema") || message.Contains("alembic"))
        {
            return "Схема базы не совместима с подготовленным runtime профиля.";
        }
        if (message.Contains("another hermes instance") || message.Contains("port 8000"))
        {
            return "Другой экземпляр Hermes уже использует локальный порт. Остановите его и обновите проверку.";
        }
        if (message.Contains("guarded startup") || message.Contains("not a hermes finance runtime"))
        {
            return "Выбранный профиль не является подготовленным runtime Hermes Finance.";
        }
        if (message.Contains("dependency") || message.Contains("npm") || message.Contains("uv "))
        {
            return "Проверка локальных зависимостей не пройдена. Установите или восстановите инструменты и повторите проверку.";
        }
        if (message.Contains("access") || message.Contains("permission"))
        {
            return "Launcher не может безопасно прочитать или использовать данные профиля.";
        }
        if (message.Contains("does not exist") || message.Contains("missing"))
        {
            return "В подготовленном профиле не хватает обязательного runtime-файла или каталога.";
        }
        return "Preflight-проверка не пройдена. Откройте «Диагностика и логи» для технического контекста.";
    }

    public static string CheckValue(bool passed, string success, string failure = "Требует внимания") =>
        passed ? success : failure;

    public static Color AccentFor(string type) => type.Equals("stable", StringComparison.OrdinalIgnoreCase)
        ? Color.FromArgb(102, 227, 190)
        : Color.FromArgb(190, 165, 255);

    public static Color CardBackgroundFor(string type) => type.Equals("stable", StringComparison.OrdinalIgnoreCase)
        ? Color.FromArgb(21, 43, 50)
        : Color.FromArgb(37, 32, 59);

    public static Color StatusColor(LauncherReadinessState state) => state switch
    {
        LauncherReadinessState.Ready or LauncherReadinessState.Running => Color.FromArgb(102, 227, 190),
        LauncherReadinessState.NeedsPreparation or LauncherReadinessState.Starting => Color.FromArgb(255, 196, 116),
        LauncherReadinessState.Blocked => Color.FromArgb(255, 125, 139),
        LauncherReadinessState.Stopped => Color.FromArgb(190, 165, 255),
        _ => Color.FromArgb(148, 161, 181),
    };
}

internal sealed class ProfileCard : Panel
{
    private readonly Label _badge = new();
    private readonly Label _name = new();
    private readonly Label _description = new();
    private readonly Label _dataBoundary = new();
    private readonly Label _status = new();
    private LauncherReadinessState _state = LauncherReadinessState.NotChecked;
    private bool _selected;

    public ProfileCard(LauncherProfile profile)
    {
        Profile = profile;
        AccessibleRole = AccessibleRole.RadioButton;
        AccessibleName = profile.DisplayName;
        Cursor = Cursors.Hand;
        Margin = new Padding(6, 4, 6, 6);
        Height = 146;
        BackColor = LauncherUi.CardBackgroundFor(profile.Type);
        SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer, true);

        _badge.Text = LauncherUi.TypeBadge(profile.Type);
        _badge.Font = new Font("Segoe UI", 8.5F, FontStyle.Bold);
        _badge.ForeColor = LauncherUi.AccentFor(profile.Type);
        _badge.AutoSize = true;

        _name.Text = profile.DisplayName;
        _name.Font = new Font("Segoe UI", 14F, FontStyle.Bold);
        _name.ForeColor = Color.FromArgb(245, 248, 252);
        _name.AutoEllipsis = true;
        _name.Dock = DockStyle.Fill;

        _description.Text = $"{LauncherUi.CardDescription(profile.Type)}  •  {LauncherUi.ReleaseBadge(profile.ExpectedRef)}";
        _description.Font = new Font("Segoe UI", 9F);
        _description.ForeColor = Color.FromArgb(193, 204, 220);
        _description.AutoEllipsis = true;
        _description.Dock = DockStyle.Fill;

        _dataBoundary.Text = LauncherUi.DataBoundary(profile.Type);
        _dataBoundary.Font = new Font("Segoe UI", 9F);
        _dataBoundary.ForeColor = Color.FromArgb(160, 175, 196);
        _dataBoundary.AutoEllipsis = true;
        _dataBoundary.Dock = DockStyle.Fill;

        _status.Text = LauncherUi.ReadinessLabel(_state);
        _status.Font = new Font("Segoe UI", 8.5F, FontStyle.Bold);
        _status.ForeColor = LauncherUi.StatusColor(_state);
        _status.AutoSize = true;
        _status.Anchor = AnchorStyles.Left | AnchorStyles.Bottom;

        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 5,
            Padding = new Padding(16, 12, 16, 10),
            BackColor = Color.Transparent,
        };
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 20));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 30));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 22));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 22));
        layout.Controls.Add(_badge, 0, 0);
        layout.Controls.Add(_name, 0, 1);
        layout.Controls.Add(_description, 0, 2);
        layout.Controls.Add(_dataBoundary, 0, 3);
        layout.Controls.Add(_status, 0, 4);
        Controls.Add(layout);
        WireClick(this);
        Resize += (_, _) => SetRoundedRegion();
        SetRoundedRegion();
    }

    public LauncherProfile Profile { get; }

    public event EventHandler? Selected;

    public void SetSelected(bool selected)
    {
        _selected = selected;
        Invalidate();
    }

    public void SetState(LauncherReadinessState state)
    {
        _state = state;
        _status.Text = LauncherUi.ReadinessLabel(state);
        _status.ForeColor = LauncherUi.StatusColor(state);
        AccessibleDescription = $"{Profile.DisplayName}: {_status.Text}";
        Invalidate();
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
        using var path = RoundedPath(new Rectangle(0, 0, Math.Max(1, Width - 1), Math.Max(1, Height - 1)), 14);
        using var pen = new Pen(_selected ? LauncherUi.AccentFor(Profile.Type) : Color.FromArgb(60, 77, 101), _selected ? 2.2F : 1F);
        e.Graphics.DrawPath(pen, path);
    }

    protected override void OnKeyDown(KeyEventArgs e)
    {
        if (e.KeyCode is Keys.Enter or Keys.Space)
        {
            Selected?.Invoke(this, EventArgs.Empty);
            e.Handled = true;
            return;
        }
        base.OnKeyDown(e);
    }

    private void WireClick(Control control)
    {
        control.Click += (_, _) => Selected?.Invoke(this, EventArgs.Empty);
        foreach (Control child in control.Controls)
        {
            WireClick(child);
        }
    }

    private void SetRoundedRegion()
    {
        if (Width <= 0 || Height <= 0)
        {
            return;
        }
        using var path = RoundedPath(new Rectangle(0, 0, Width, Height), 14);
        Region = new Region(path);
    }

    private static GraphicsPath RoundedPath(Rectangle bounds, int radius)
    {
        var path = new GraphicsPath();
        var diameter = radius * 2;
        path.AddArc(bounds.X, bounds.Y, diameter, diameter, 180, 90);
        path.AddArc(bounds.Right - diameter, bounds.Y, diameter, diameter, 270, 90);
        path.AddArc(bounds.Right - diameter, bounds.Bottom - diameter, diameter, diameter, 0, 90);
        path.AddArc(bounds.X, bounds.Bottom - diameter, diameter, diameter, 90, 90);
        path.CloseFigure();
        return path;
    }
}
