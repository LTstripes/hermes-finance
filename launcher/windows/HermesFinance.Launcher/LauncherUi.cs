using System.Drawing.Drawing2D;

namespace HermesFinance.Launcher;

internal enum LauncherReadinessState
{
    NotChecked,
    Checking,
    Ready,
    NeedsPreparation,
    Blocked,
    Preparing,
    Repairing,
    Starting,
    Updating,
    Running,
    Stopped,
}

internal enum LauncherPrimaryAction
{
    None,
    Update,
    UpdateAndStart,
    Prepare,
    Repair,
    Start,
    Open,
    Stop,
    Refresh,
}

internal sealed record LauncherActionPlan(LauncherPrimaryAction Primary, string Reason, string HumanSummary);

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
        "stable" => "Pinned production runtime",
        "preview" => "Unreleased main  ·  isolated",
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

        if (value.StartsWith("refs/remotes/", StringComparison.OrdinalIgnoreCase))
        {
            value = value["refs/remotes/".Length..];
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

    public static string StableIdentityLabel(LauncherProfile profile, string? headSha)
    {
        var release = ReleaseBadge(profile.ExpectedRef);
        var sha = string.IsNullOrWhiteSpace(headSha) ? "—" : headSha[..Math.Min(7, headSha.Length)];
        // Stable must show pinned release identity clearly
        return $"{release}  ·  {sha}  ·  {DataBoundary(profile.Type)}";
    }

    public static string PreviewIdentityLabel(LauncherProfile profile, string? currentSha, string? targetSha)
    {
        var cur = string.IsNullOrWhiteSpace(currentSha) ? "—" : currentSha[..Math.Min(7, currentSha.Length)];
        var tgt = string.IsNullOrWhiteSpace(targetSha) ? "not fetched" : targetSha[..Math.Min(7, targetSha.Length)];
        var unreleased = "UNRELEASED";
        if (!string.IsNullOrWhiteSpace(targetSha) && !string.IsNullOrWhiteSpace(currentSha)
            && targetSha.Equals(currentSha, StringComparison.OrdinalIgnoreCase))
        {
            return $"main {cur} · {unreleased} · {DataBoundary(profile.Type)}";
        }
        return $"main {cur} → {tgt} · {unreleased} · {DataBoundary(profile.Type)}";
    }

    public static string ShaShort(string? sha) => string.IsNullOrWhiteSpace(sha) ? "—" : sha[..Math.Min(7, sha.Length)];

    public static string ReadinessLabel(LauncherReadinessState state) => state switch
    {
        LauncherReadinessState.NotChecked => "НЕ ПРОВЕРЕНО",
        LauncherReadinessState.Checking => "ПРОВЕРЯЕМ",
        LauncherReadinessState.Ready => "ГОТОВО",
        LauncherReadinessState.NeedsPreparation => "НУЖНА ПОДГОТОВКА",
        LauncherReadinessState.Blocked => "ЗАБЛОКИРОВАНО",
        LauncherReadinessState.Preparing => "ПОДГОТАВЛИВАЕМ",
        LauncherReadinessState.Repairing => "ИСПРАВЛЯЕМ",
        LauncherReadinessState.Starting => "ЗАПУСКАЕМ",
        LauncherReadinessState.Updating => "ОБНОВЛЯЕМ",
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
        LauncherReadinessState.Preparing => "Подготавливаем зависимости",
        LauncherReadinessState.Repairing => "Исправляем зависимости",
        LauncherReadinessState.Starting => "Hermes запускается",
        LauncherReadinessState.Updating => "Обновляем Preview",
        LauncherReadinessState.Running => "Hermes работает",
        LauncherReadinessState.Stopped => "Hermes остановлен",
        _ => "Проверка ещё не запускалась",
    };

    public static string ReadinessDescription(LauncherReadinessState state) => state switch
    {
        LauncherReadinessState.NotChecked => "Выберите профиль, чтобы проверить его готовность.",
        LauncherReadinessState.Checking => "Проверяем runtime, данные, зависимости и loopback-порт.",
        LauncherReadinessState.Ready => "Все проверки пройдены. Можно запускать Hermes.",
        LauncherReadinessState.NeedsPreparation => "Нажмите «Подготовить» — установка только locked-зависимостей этого профиля.",
        LauncherReadinessState.Blocked => "Исправьте blocker в подготовленном runtime и повторите проверку. Подсказка ниже — какое launcher-действие исправляет это.",
        LauncherReadinessState.Preparing => "Выполняем owner-triggered установку только locked-зависимостей выбранного профиля.",
        LauncherReadinessState.Repairing => "Принудительно восстанавливаем только locked-зависимости выбранного профиля.",
        LauncherReadinessState.Starting => "Ждём штатные health probes существующего guarded startup.",
        LauncherReadinessState.Updating => "Получаем canonical origin/main и обновляем только настроенный Preview checkout.",
        LauncherReadinessState.Running => "Сервис доступен только локально на 127.0.0.1:8000.",
        LauncherReadinessState.Stopped => "Профиль остановлен. Можно снова выполнить preflight.",
        _ => "Выберите профиль, чтобы проверить его готовность.",
    };

    public static string OwnerFacingFailure(string rawMessage)
    {
        var message = rawMessage.ToLowerInvariant();
        if (message.Contains("only one production profile") || message.Contains("exactly one stable"))
        {
            return "Конфигурация должна содержать ровно один Stable-профиль. Исправьте config.json через launcher (Открыть папку) или переустановите launcher.";
        }
        if (message.Contains("launcher config") || message.Contains("config is invalid"))
        {
            return "Конфигурация launcher невалидна. Launcher попробует создать/мигрировать её автоматически где безопасно; иначе откройте «Диагностика» и нажмите «Обновить проверку».";
        }
        if (message.Contains("stable may use only the production runtime"))
        {
            return "Stable должен указывать только на canonical production runtime. Исправьте путь в launcher config.";
        }
        if (message.Contains("stable may use only the production database"))
        {
            return "Stable должен использовать только canonical production database.";
        }
        if (message.Contains("cannot open production data") || message.Contains("aliases production"))
        {
            return "Preview и Experiment должны использовать собственные данные, не production. Выберите другой data_dir/database и нажмите «Обновить проверку».";
        }
        if (message.Contains("linked worktrees") || message.Contains("not independent"))
        {
            return "Профиль должен быть независимым checkout, а не linked worktree. Создайте отдельный clone.";
        }
        if (message.Contains("identity does not match"))
        {
            return "Code identity не совпадает с ожидаемой версией. Для Preview нажмите «Обновить Preview»; для Stable — проверьте expected_ref (released tag) и нажмите «Обновить проверку».";
        }
        if (message.Contains("identity is ambiguous"))
        {
            return "Заблокировано: checkout изменён (не чистый). Сделайте checkout чистым и нажмите «Обновить проверку».";
        }
        if (message.Contains("dirty or conflicted"))
        {
            return "Preview checkout изменён или содержит конфликт. Нажмите «Обновить проверку» после очистки или «Исправить» если нужно восстановить зависимости.";
        }
        if (message.Contains("unexpected; update is blocked"))
        {
            return "Preview checkout не совпадает с ожидаемой подготовленной версией. Обновление заблокировано — сделайте checkout чистым и повторите.";
        }
        if (message.Contains("origin/main") && message.Contains("update"))
        {
            return "Preview не удалось безопасно обновить до canonical origin/main. Проверьте сеть и нажмите «Обновить Preview» снова.";
        }
        if (message.Contains("sidecar") || message.Contains("unstamped data"))
        {
            return "Identity данных не подтверждён. Нужен корректный sidecar для этого профиля — запустите Hermes один раз через launcher или создайте UAT-копию как в docs.";
        }
        if (message.Contains("schema") || message.Contains("alembic"))
        {
            return "Схема базы не совместима с подготовленным runtime профиля. Проверьте базу/миграции, затем «Обновить проверку». При нужде — «Исправить» для зависимостей.";
        }
        if (message.Contains("another hermes instance") || message.Contains("port 8000"))
        {
            return "Другой экземпляр Hermes уже использует локальный порт. Нажмите «Остановить» или остановите другой процесс и «Обновить проверку».";
        }
        if (message.Contains("guarded startup") || message.Contains("not a hermes finance runtime"))
        {
            return "Выбранный профиль не является подготовленным runtime Hermes Finance. Проверьте пути checkout.";
        }
        if (message.Contains("dependency") || message.Contains("npm") || message.Contains("uv "))
        {
            return "Проверка зависимостей не пройдена. Нажмите «Подготовить» или «Исправить», если launcher может восстановить этот профиль.";
        }
        if (message.Contains("access") || message.Contains("permission"))
        {
            return "Launcher не может безопасно прочитать или использовать данные профиля. Проверьте права/.hermes-data-identity.json.";
        }
        if (message.Contains("does not exist") || message.Contains("missing"))
        {
            return "В подготовленном профиле не хватает runtime-файла/каталога. Проверьте checkout и «Обновить проверку».";
        }
        return "Preflight-проверка не пройдена. Launcher покажет точное действие ниже — нажмите его или откройте «Диагностика».";
    }

    public static LauncherActionPlan PlanPrimaryAction(
        LauncherReadinessState state,
        ValidatedProfile? validated,
        LauncherProfile profile,
        Exception? blockedException = null)
    {
        if (state == LauncherReadinessState.Running)
        {
            return new(LauncherPrimaryAction.Stop, "Hermes работает — можно остановить или открыть.", "Hermes запущен на 127.0.0.1:8000");
        }
        if (state == LauncherReadinessState.Ready)
        {
            // Running already handled; Ready means validated and deps ready
            return new(LauncherPrimaryAction.Start, "Готово к запуску", "Preflight пройден — нажмите «Запустить»");
        }
        if (state == LauncherReadinessState.NeedsPreparation)
        {
            return new(LauncherPrimaryAction.Prepare, "Зависимости требуют подготовки", "Locked зависимости не готовы — нажмите «Подготовить» (offline проверка, сеть только по явному нажатию)");
        }
        if (state == LauncherReadinessState.Blocked && blockedException is not null)
        {
            var msg = blockedException.Message.ToLowerInvariant();
            var isPreview = profile.Type.Equals("preview", StringComparison.OrdinalIgnoreCase);
            if (msg.Contains("identity does not match") && isPreview)
            {
                return new(LauncherPrimaryAction.Update, "Code identity не совпадает — нужно обновление Preview", "Preview отстал от canonical origin/main — нажмите «Обновить Preview»");
            }
            if (msg.Contains("dirty or conflicted") && isPreview)
            {
                return new(LauncherPrimaryAction.Refresh, "Заблокировано: checkout изменён", "Сделайте checkout чистым и «Обновить проверку»");
            }
            if ((msg.Contains("dependency") || msg.Contains("npm") || msg.Contains("uv ")) )
            {
                return new(LauncherPrimaryAction.Prepare, "Зависимости не готовы", "Нажмите «Подготовить» или «Исправить»");
            }
            if (msg.Contains("another hermes instance") || msg.Contains("port 8000"))
            {
                return new(LauncherPrimaryAction.Stop, "Порт занят", "Остановите другой Hermes и «Обновить проверку»");
            }
            if (msg.Contains("sidecar") || msg.Contains("unstamped"))
            {
                return new(LauncherPrimaryAction.Refresh, "Данные не подтверждены", "sidecar не совпадает — см. «Диагностика», затем «Обновить проверку»");
            }
            if (msg.Contains("schema") || msg.Contains("alembic"))
            {
                return new(LauncherPrimaryAction.Refresh, "Схема не совместима", "Проверьте DB/миграции — потом «Обновить проверку»");
            }
        }
        if (state == LauncherReadinessState.Blocked)
        {
            return new(LauncherPrimaryAction.Refresh, "Заблокировано", "Исправьте blocker и «Обновить проверку»");
        }
        // Preview behind origin/main but still Ready? Offer update-and-start as primary
        if (validated?.PreviewUpdate is not null && !validated.PreviewUpdate.IsCurrent && validated.Dependencies?.Ready == true)
        {
            return new(LauncherPrimaryAction.Update, "Preview отстал — доступно обновление", "Preview можно обновить до canonical origin/main");
        }
        return new(LauncherPrimaryAction.Refresh, "Проверка не запускалась", "Нажмите «Обновить проверку»");
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
        LauncherReadinessState.NeedsPreparation or LauncherReadinessState.Preparing or LauncherReadinessState.Repairing or LauncherReadinessState.Starting or LauncherReadinessState.Updating => Color.FromArgb(255, 196, 116),
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
    private readonly Label _identity = new();
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
        Height = 168;
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

        var isStable = profile.Type.Equals("stable", StringComparison.OrdinalIgnoreCase);
        var isPreview = profile.Type.Equals("preview", StringComparison.OrdinalIgnoreCase);
        string desc;
        if (isStable)
        {
            desc = $"Pinned {LauncherUi.ReleaseBadge(profile.ExpectedRef)}  ·  production";
        }
        else if (isPreview)
        {
            desc = $"main / unreleased  ·  {LauncherUi.DataBoundary(profile.Type)}";
        }
        else
        {
            desc = $"{LauncherUi.CardDescription(profile.Type)}  ·  {LauncherUi.ReleaseBadge(profile.ExpectedRef)}";
        }
        _description.Text = desc;
        _description.Font = new Font("Segoe UI", 9F);
        _description.ForeColor = Color.FromArgb(193, 204, 220);
        _description.AutoEllipsis = true;
        _description.Dock = DockStyle.Fill;

        _dataBoundary.Text = profile.Type.Equals("stable", StringComparison.OrdinalIgnoreCase)
            ? "Canonical production data  ·  Stable"
            : LauncherUi.DataBoundary(profile.Type) + (isPreview ? "  ·  UNRELEASED" : "");
        _dataBoundary.Font = new Font("Segoe UI", 8F, FontStyle.Bold);
        _dataBoundary.ForeColor = isStable ? Color.FromArgb(102, 227, 190) : isPreview ? Color.FromArgb(255, 196, 116) : Color.FromArgb(160, 175, 196);
        _dataBoundary.AutoEllipsis = true;
        _dataBoundary.Dock = DockStyle.Fill;

        _identity.Text = isStable
            ? LauncherUi.StableIdentityLabel(profile, null)
            : isPreview ? LauncherUi.PreviewIdentityLabel(profile, null, null) : LauncherUi.ReleaseBadge(profile.ExpectedRef);
        _identity.Font = new Font("Cascadia Mono", 7.5F);
        _identity.ForeColor = Color.FromArgb(164, 190, 225);
        _identity.AutoEllipsis = true;
        _identity.Dock = DockStyle.Fill;

        _status.Text = LauncherUi.ReadinessLabel(_state);
        _status.Font = new Font("Segoe UI", 8.5F, FontStyle.Bold);
        _status.ForeColor = LauncherUi.StatusColor(_state);
        _status.AutoSize = true;
        _status.Anchor = AnchorStyles.Left | AnchorStyles.Bottom;

        var layout = new TableLayoutPanel
        {
            Dock = DockStyle.Fill,
            ColumnCount = 1,
            RowCount = 6,
            Padding = new Padding(16, 12, 16, 10),
            BackColor = Color.Transparent,
        };
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 20));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 30));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 22));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 18));
        layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
        layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 22));
        layout.Controls.Add(_badge, 0, 0);
        layout.Controls.Add(_name, 0, 1);
        layout.Controls.Add(_description, 0, 2);
        layout.Controls.Add(_identity, 0, 3);
        layout.Controls.Add(_dataBoundary, 0, 4);
        layout.Controls.Add(_status, 0, 5);
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

    public void SetIdentity(string? headSha, string? targetSha)
    {
        var isStable = Profile.Type.Equals("stable", StringComparison.OrdinalIgnoreCase);
        var isPreview = Profile.Type.Equals("preview", StringComparison.OrdinalIgnoreCase);
        if (isStable)
        {
            _identity.Text = LauncherUi.StableIdentityLabel(Profile, headSha);
        }
        else if (isPreview)
        {
            _identity.Text = LauncherUi.PreviewIdentityLabel(Profile, headSha, targetSha);
        }
        else
        {
            _identity.Text = headSha is not null ? $"SHA {LauncherUi.ShaShort(headSha)}" : LauncherUi.ReleaseBadge(Profile.ExpectedRef);
        }
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
