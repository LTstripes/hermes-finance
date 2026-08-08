import type { ReactNode } from "react";

type StateBlockProps = {
  title: string;
  description: string;
  icon?: ReactNode;
  inline?: boolean;
};

export function LoadingState({
  title = "Загрузка",
  description = "Загружаем данные…",
  inline = false,
}: Partial<StateBlockProps>) {
  return (
    <div className={`state-block${inline ? " state-block--inline" : ""}`} role="status">
      <div aria-hidden="true" className="spinner" />
      <strong>{title}</strong>
      <span>{description}</span>
    </div>
  );
}

export function ErrorState({
  title = "Ошибка",
  description = "Что-то пошло не так",
  inline = false,
}: Partial<StateBlockProps>) {
  return (
    <div className={`state-block${inline ? " state-block--inline" : ""}`} role="alert">
      <div aria-hidden="true" className="state-icon state-icon--error">
        !
      </div>
      <strong>{title}</strong>
      <span>{description}</span>
    </div>
  );
}

export function EmptyState({
  title = "Пусто",
  description = "Пока нет данных",
  inline = false,
  action,
}: Partial<StateBlockProps> & { action?: ReactNode }) {
  return (
    <div className={`state-block${inline ? " state-block--inline" : ""}`}>
      <div aria-hidden="true" className="state-icon state-icon--empty">
        ∅
      </div>
      <strong>{title}</strong>
      <span>{description}</span>
      {action}
    </div>
  );
}
