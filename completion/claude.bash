# Claude Cortex - Bash Autocompletion
# Provides contextual completion for commands, profiles, flags, and shortcuts

_claude_completions() {
    local cur prev
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    local subcommands="continue switch docs status quota clean profile login menu whoami dream palace remember recall provider model update test bench reasoning effort research discovery think smart cognition turbo fast"
    local flags="-y --yes -s --sonnet -o --opus -h --haiku -t --turbo --fast -d --dream -e --effort -r --reasoning --think-low --think-med --think-high --think-max --think-off --provider --api-key -m --menu --help --version --print --resume --dangerously-skip-permissions"
    
    # Dynamically gather configured profiles
    local profiles=()
    local profile_flags=()
    local prof_dir="${HOME}/.claude-profiles"
    if [ -d "$prof_dir" ]; then
        local idx=1
        for p in "$prof_dir"/*; do
            if [ -d "$p" ]; then
                local bname
                bname=$(basename "$p")
                if [ "$bname" != "." ] && [ "$bname" != ".." ]; then
                    profiles+=("$bname")
                    profile_flags+=("-$bname" "--$bname" "-p${idx}")
                    idx=$((idx + 1))
                fi
            fi
        done
    fi

    # Subcommand and root-level completion
    if [ "$COMP_CWORD" -eq 1 ]; then
        local all_suggestions="$subcommands ${profiles[*]} ${profile_flags[*]} -1 -2 -3 $flags"
        COMPREPLY=( $(compgen -W "$all_suggestions" -- "$cur") )
        return 0
    fi

    # Contextual completion based on previous command
    case "$prev" in
        switch|login|continue)
            local target_suggestions="${profiles[*]} 1 2 3"
            COMPREPLY=( $(compgen -W "$target_suggestions" -- "$cur") )
            return 0
            ;;
        dream)
            COMPREPLY=( $(compgen -W "run --quick --chambers tech biz psych creative" -- "$cur") )
            return 0
            ;;
        palace)
            COMPREPLY=( $(compgen -W "status map remember recall auto-recall prune consolidate" -- "$cur") )
            return 0
            ;;
        profile|profiles)
            COMPREPLY=( $(compgen -W "add remove list switch status" -- "$cur") )
            return 0
            ;;
        provider|providers)
            COMPREPLY=( $(compgen -W "status set config env reset" -- "$cur") )
            return 0
            ;;
        model|models)
            COMPREPLY=( $(compgen -W "list free paid set info search" -- "$cur") )
            return 0
            ;;
        update|upgrade)
            COMPREPLY=( $(compgen -W "check apply status" -- "$cur") )
            return 0
            ;;
        set)
            if [ "${COMP_WORDS[COMP_CWORD-2]}" = "provider" ]; then
                COMPREPLY=( $(compgen -W "oauth anthropic openrouter gemini" -- "$cur") )
                return 0
            fi
            ;;
        config)
            if [ "${COMP_WORDS[COMP_CWORD-2]}" = "provider" ]; then
                COMPREPLY=( $(compgen -W "anthropic openrouter gemini" -- "$cur") )
                return 0
            fi
            ;;
        --provider)
            COMPREPLY=( $(compgen -W "oauth anthropic openrouter gemini" -- "$cur") )
            return 0
            ;;
        reasoning|effort|-e|--effort|-r|--reasoning)
            COMPREPLY=( $(compgen -W "low medium high xhigh max off" -- "$cur") )
            return 0
            ;;
        remember|--room|-r)
            COMPREPLY=( $(compgen -W "blueprint procedures graveyard decisions working" -- "$cur") )
            return 0
            ;;
        remove|rm|delete)
            if [ "${COMP_WORDS[COMP_CWORD-2]}" = "profile" ] || [ "${COMP_WORDS[COMP_CWORD-2]}" = "profiles" ]; then
                COMPREPLY=( $(compgen -W "${profiles[*]}" -- "$cur") )
                return 0
            fi
            ;;
    esac
}

complete -F _claude_completions claude cc

bind "set show-all-if-ambiguous on" 2>/dev/null || true
bind "set completion-ignore-case on" 2>/dev/null || true
