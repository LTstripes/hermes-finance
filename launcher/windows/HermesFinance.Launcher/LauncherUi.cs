using System.Text.RegularExpressions;

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

internal enum LauncherPrimaryAction
{
    None,
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

    public static string ChoiceLabel(string type) => type.ToLowerInvariant() switch
    {
        "stable" => "Stable · production",
        "preview" => "Preview · isolated",
        "experiment" => "Experiment · sandbox",
        _ => "Profile",
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

    // #302: owner-facing card/selected titles must never contradict the
    // validated release identity. Older installs may carry a stale version
    // inside display_name (e.g. "Hermes Finance — Stable 0.8.0" or
    // "0.7 Preview"); the version lives ONLY in the validated identity
    // lines (ReleaseBadge/StableIdentityLabel/PreviewIdentityLabel), so the
    // title is the display name with any stale version token stripped.
    private static readonly Regex LeadingVersionToken = new(
        @"^\s*v?\d+\.\d+(\.\d+)?\s+",
        RegexOptions.Compiled | RegexOptions.CultureInvariant);

    private static readonly Regex TrailingVersionToken = new(
        @"\s+v?\d+\.\d+(\.\d+)?\s*$",
        RegexOptions.Compiled | RegexOptions.CultureInvariant);

    public static string OwnerTitle(LauncherProfile profile)
    {
        // #302: Stable/Preview are owner-facing product profiles, not custom
        // labels. Rebuild their title from the validated type so legacy
        // display_name values cannot leak mojibake or stale version tokens.
        var type = profile.Type.Trim().ToLowerInvariant();
        if (type is "stable" or "preview")
        {
            var profileLabel = type is "stable" ? "Stable" : "Preview";
            return $"Hermes Finance — {profileLabel}";
        }

        var raw = (profile.DisplayName ?? string.Empty).Trim();
        var clean = TrailingVersionToken.Replace(LeadingVersionToken.Replace(raw, string.Empty), string.Empty).Trim();
        return string.IsNullOrWhiteSpace(clean) ? raw : clean;
    }

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

    public static string StableIdentityLabel(LauncherProfile profile, string? headSha, string? applicationVersion = null)
    {
        var release = IsExactCommit(profile.ExpectedRef) && !string.IsNullOrWhiteSpace(applicationVersion)
            ? $"Version {applicationVersion}"
            : ReleaseBadge(profile.ExpectedRef);
        var sha = string.IsNullOrWhiteSpace(headSha) ? "—" : headSha[..Math.Min(7, headSha.Length)];
        return $"{release}  ·  SHA {sha}  ·  {DataBoundary(profile.Type)}";
    }

    private static bool IsExactCommit(string expectedRef) =>
        expectedRef.Length == 40 && expectedRef.All(static character => char.IsAsciiHexDigit(character));

    public static string PreviewIdentityLabel(LauncherProfile profile, string? currentSha)
    {
        var cur = string.IsNullOrWhiteSpace(currentSha) ? "—" : currentSha[..Math.Min(7, currentSha.Length)];
        return $"main {cur} · UNRELEASED · {DataBoundary(profile.Type)}";
    }

    public static string ShaShort(string? sha) => string.IsNullOrWhiteSpace(sha) ? "—" : sha[..Math.Min(7, sha.Length)];

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
        LauncherReadinessState.NotChecked => "Не проверено",
        LauncherReadinessState.Checking => "Проверяем",
        LauncherReadinessState.Ready => "Готов",
        LauncherReadinessState.NeedsPreparation => "Нужна подготовка",
        LauncherReadinessState.Blocked => "Заблокировано",
        LauncherReadinessState.Starting => "Запускается",
        LauncherReadinessState.Running => "Работает",
        LauncherReadinessState.Stopped => "Остановлено",
        _ => "Не проверено",
    };

    public static string ReadinessDescription(LauncherReadinessState state) => state switch
    {
        LauncherReadinessState.NotChecked => "Выберите среду.",
        LauncherReadinessState.Checking => "Проверяем подготовленную среду.",
        LauncherReadinessState.Ready => "Можно запускать.",
        LauncherReadinessState.NeedsPreparation => "Зависимости не готовы. Нужен внешний OPS01 Prepare.",
        LauncherReadinessState.Blocked => "Запуск заблокирован.",
        LauncherReadinessState.Starting => "Ждём локальный запуск.",
        LauncherReadinessState.Running => "Только 127.0.0.1:8000.",
        LauncherReadinessState.Stopped => "Остановлено.",
        _ => "Выберите среду.",
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
            return "Конфигурация launcher отсутствует или невалидна. Нажмите «Настроить…» и выберите Stable/Preview каталоги через launcher; ручной JSON — только recovery-only.";
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
            return "Code identity не совпадает с ожидаемой версией. Проверьте configured expected_ref и нажмите «Обновить проверку».";
        }
        if (message.Contains("identity is ambiguous"))
        {
            return "Заблокировано: checkout изменён (не чистый). Сделайте checkout чистым и нажмите «Обновить проверку».";
        }
        if (message.Contains("dirty or conflicted"))
        {
            return "Checkout изменён или содержит конфликт. Очистите подготовленный runtime вне launcher и нажмите «Обновить проверку».";
        }
        if (message.Contains("unexpected; update is blocked"))
        {
            return "Checkout не совпадает с ожидаемой подготовленной версией. Действие заблокировано — проверьте configured expected_ref и повторите.";
        }
        if (message.Contains("sidecar") || message.Contains("unstamped data"))
        {
            return "Identity данных не подтверждён. Нужен корректный sidecar для этого профиля — запустите Hermes один раз через launcher или создайте UAT-копию как в docs.";
        }
        if (message.Contains("schema") || message.Contains("alembic"))
        {
            return "Схема базы не совместима с подготовленным runtime профиля. Проверьте базу/миграции, затем «Обновить проверку».";
        }
        if (message.Contains("another hermes instance") || message.Contains("port 8000"))
        {
            return "Локальный порт 127.0.0.1:8000 занят другим процессом. Launcher не останавливает чужие процессы: остановите другой Hermes вручную и нажмите «Обновить проверку».";
        }
        if (message.Contains("guarded startup") || message.Contains("not a hermes finance runtime"))
        {
            return "Выбранный профиль не является подготовленным runtime Hermes Finance. Проверьте пути checkout.";
        }
        if (message.Contains("dependency") || message.Contains("npm") || message.Contains("uv "))
        {
            return "Проверка зависимостей не пройдена. Launcher не меняет runtime: выполните OPS01 Prepare во внешнем подготовленном runtime и обновите проверку.";
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
            return new(LauncherPrimaryAction.Open, "Hermes работает", "Локально на 127.0.0.1:8000");
        }
        if (state == LauncherReadinessState.Ready)
        {
            return new(LauncherPrimaryAction.Start, "Готово к запуску", "Preflight пройден — нажмите «Запустить»");
        }
        if (state == LauncherReadinessState.NeedsPreparation)
        {
            return new(LauncherPrimaryAction.Refresh, "Зависимости требуют внешней подготовки", "Locked зависимости не готовы — выполните OPS01 Prepare во внешнем подготовленном runtime, затем «Обновить проверку»");
        }
        if (state == LauncherReadinessState.Blocked && blockedException is not null)
        {
            var msg = blockedException.Message.ToLowerInvariant();
            var isStable = profile.Type.Equals("stable", StringComparison.OrdinalIgnoreCase);
            if (msg.Contains("identity does not match") && isStable)
            {
                // Stable is pinned: launcher never updates Stable, so a mismatch
                // is recovery-only. Refresh re-checks; the fix happens outside
                // the launcher (verify released tag / reinstall Stable).
                return new(LauncherPrimaryAction.Refresh, "Stable code identity не совпадает", "Проверьте подготовленный опубликованный Stable runtime и нажмите «Обновить проверку»");
            }
            if (msg.Contains("identity is ambiguous") && isStable)
            {
                return new(LauncherPrimaryAction.Refresh, "Stable checkout изменён", "Сделайте Stable checkout чистым и нажмите «Обновить проверку»");
            }
            if (msg.Contains("dirty or conflicted"))
            {
                return new(LauncherPrimaryAction.Refresh, "Заблокировано: checkout изменён", "Сделайте checkout чистым и «Обновить проверку»");
            }
            if ((msg.Contains("dependency") || msg.Contains("npm") || msg.Contains("uv ")) )
            {
                return new(LauncherPrimaryAction.Refresh, "Зависимости не готовы", "Выполните OPS01 Prepare во внешнем подготовленном runtime, затем «Обновить проверку»");
            }
            if (msg.Contains("another hermes instance") || msg.Contains("port 8000"))
            {
                // External port collision: launcher owns no process to stop, so
                // Stop would be a false action. Refresh is the honest primary.
                return new(LauncherPrimaryAction.Refresh, "Порт занят внешним процессом", "Порт 127.0.0.1:8000 занят другим процессом — launcher не останавливает чужие процессы. Остановите его вручную и «Обновить проверку»");
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
        LauncherReadinessState.NeedsPreparation or LauncherReadinessState.Starting => Color.FromArgb(255, 196, 116),
        LauncherReadinessState.Blocked => Color.FromArgb(255, 125, 139),
        LauncherReadinessState.Stopped => Color.FromArgb(190, 165, 255),
        _ => Color.FromArgb(148, 161, 181),
    };
}

internal sealed class ProfileChoice : Panel
{
    private readonly Label _name = new();
    private bool _selected;

    public ProfileChoice(LauncherProfile profile)
    {
        Profile = profile;
        AccessibleRole = AccessibleRole.RadioButton;
        AccessibleName = LauncherUi.ChoiceLabel(profile.Type);
        Cursor = Cursors.Hand;
        Margin = new Padding(0, 0, 8, 0);
        Padding = Padding.Empty;
        TabStop = true;
        BackColor = LauncherUi.CardBackgroundFor(profile.Type);
        _name.Text = LauncherUi.ChoiceLabel(profile.Type);
        _name.ForeColor = LauncherUi.AccentFor(profile.Type);
        _name.BackColor = Color.Transparent;
        _name.AutoSize = false;
        _name.AutoEllipsis = false;
        _name.FontChanged += (_, _) => Fit();
        _name.Font = new Font("Segoe UI", 9F, FontStyle.Bold);
        Controls.Add(_name);
        Fit();
        WireClick(this);
    }

    private void Fit()
    {
        var text = TextRenderer.MeasureText(
            _name.Text,
            _name.Font,
            new Size(int.MaxValue, int.MaxValue),
            TextFormatFlags.SingleLine | TextFormatFlags.NoPadding);
        _name.Location = new Point(12, 8);
        _name.Size = new Size(Math.Max(1, text.Width), Math.Max(1, text.Height));
        Size = new Size(_name.Right + 12, Math.Max(34, _name.Bottom + 8));
    }

    public LauncherProfile Profile { get; }

    public event EventHandler? Selected;

    public void SetSelected(bool selected)
    {
        _selected = selected;
        Invalidate();
    }

    protected override void OnPaint(PaintEventArgs e)
    {
        base.OnPaint(e);
        using var pen = new Pen(_selected ? LauncherUi.AccentFor(Profile.Type) : Color.FromArgb(60, 77, 101), _selected ? 2F : 1F);
        e.Graphics.DrawRectangle(pen, 0, 0, Math.Max(1, Width - 1), Math.Max(1, Height - 1));
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
}
