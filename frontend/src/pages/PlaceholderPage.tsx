import { Badge, Panel } from "../components/ui";

type PlaceholderPageProps = {
  eyebrow: string;
  title: string;
  description: string;
  phaseHint: string;
  gaps?: string[];
};

export function PlaceholderPage({
  eyebrow,
  title,
  description,
  phaseHint,
  gaps = [],
}: PlaceholderPageProps) {
  return (
    <section className="stack-18">
      <header className="page-header">
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="page-header__description">{description}</p>
      </header>

      <Panel empty label="Скоро" title="Раздел ещё не реализован">
        <p>{description}</p>
        <span className="pending-badge">{phaseHint}</span>
      </Panel>

      {gaps.length > 0 ? (
        <Panel label="Заметки" title="Известные gaps">
          <ul style={{ margin: 0, paddingLeft: "1.1rem", color: "var(--muted)", lineHeight: 1.7 }}>
            {gaps.map((gap) => (
              <li key={gap}>
                <Badge tone="info">{gap}</Badge>
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}
    </section>
  );
}
