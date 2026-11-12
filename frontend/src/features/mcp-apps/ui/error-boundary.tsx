import { Component, Fragment, type ReactNode } from "react";

import { ErrorNotice, errorLabelsFor } from "./states";

/**
 * Render and start-up failures, shown with the family's one error notice instead of a blank view.
 *
 * `RenderErrorBoundary` wraps a room (or the whole app): an error thrown while that part draws is caught
 * there, the rest of the app keeps working, and "Försök igen" draws the part again from scratch. Only the
 * scope name and the error's class name are logged: an error message or stack can carry a title, a name or
 * other user data, so it is never written out or shown.
 */

type BoundaryProps = {
  locale: string;
  /** What this boundary guards ("work", "journal", "app", …); logged, never shown. */
  scope: string;
  children: ReactNode;
};

type BoundaryState = { failed: boolean; attempt: number };

export class RenderErrorBoundary extends Component<
  BoundaryProps,
  BoundaryState
> {
  state: BoundaryState = { failed: false, attempt: 0 };

  static getDerivedStateFromError(): Partial<BoundaryState> {
    return { failed: true };
  }

  componentDidCatch(error: unknown) {
    const kind = error instanceof Error ? error.name : "unknown";
    console.error("[sidekick] render failed", {
      scope: this.props.scope,
      kind,
    });
  }

  private retry = () =>
    this.setState((state) => ({ failed: false, attempt: state.attempt + 1 }));

  render() {
    if (this.state.failed)
      return (
        <ErrorNotice
          locale={this.props.locale}
          message={errorLabelsFor(this.props.locale).render}
          onRetry={this.retry}
        />
      );
    // A new key on retry remounts the guarded part, so it starts from a clean state.
    return <Fragment key={this.state.attempt}>{this.props.children}</Fragment>;
  }
}

/** The app could not start: one short, translated card with "Försök igen". No detail of the failure is shown. */
export function StartupError({
  locale,
  onRetry,
  retrying = false,
}: {
  locale: string;
  onRetry: () => void;
  retrying?: boolean;
}) {
  return (
    <section className="sk-card">
      <ErrorNotice
        locale={locale}
        message={errorLabelsFor(locale).startup}
        onRetry={onRetry}
        retrying={retrying}
      />
    </section>
  );
}
