# Optional Waybar integration

Momentum Pact can expose a continuously updating Waybar custom module. This is
an optional Linux desktop integration and is not part of the primary setup path.

The launcher emits Waybar-compatible JSON and watches the accountability data
file directly. It does not restart or signal Waybar when commitments change.

```jsonc
{
  "custom/momentum-pact": {
    "return-type": "json",
    "exec": "$HOME/dev/momentum-pact/scripts/momentum-pact-waybar",
    "on-click": "$HOME/dev/momentum-pact/scripts/open-momentum-pact"
  }
}
```

The status text uses Nerd Font glyphs. Its counters are mutually exclusive:
overdue, due soon, check-in due, and remaining active commitments are never
double counted. Overdue changes the module class while each count retains its
own semantic color.

Run a single payload manually with:

```sh
python3 -m momentum_pact.integrations.waybar
```

Stream updates with:

```sh
python3 -m momentum_pact.integrations.waybar --watch
```
