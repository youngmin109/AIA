import type { SlashCommand } from './slashCommands'

/** Slash command list shown above the composer while the first word is typed. */
export function CommandPalette({ commands, active, onPick }: { commands: SlashCommand[]; active: number; onPick: (command: SlashCommand) => void }) {
  return (
    <div className="command-palette glass-card" role="listbox" aria-label="명령">
      {commands.map((command, index) => (
        <button
          key={command.name}
          type="button"
          role="option"
          aria-selected={index === active}
          className="command-option"
          // Keep focus in the composer so typing continues.
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => onPick(command)}
        >
          <code>/{command.name}</code>
          <strong>{command.label}</strong>
          <span className="muted">{command.description}</span>
          {command.group === 'aia' && <span className="badge is-neutral">AIA</span>}
        </button>
      ))}
    </div>
  )
}
