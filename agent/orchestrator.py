from inference.nebius_client import call_nemotron

def build_summary_prompt(flagged_moves):
    """
    Formats flagged moves into a readable text block and returns a messages list.
    """
    move_details = ""
    for move in flagged_moves:
        move_details += (
            f"- Phase: {move.get('phase')}, Eval Loss: {move.get('eval_loss')}, "
            f"Move: {move.get('move')}, Best Move: {move.get('best_move')}\n"
        )

    system_message = (
        "You are a professional chess coach. Analyze the following sequence of mistakes "
        "made by a player. Instead of just listing them, identify recurring patterns, "
        "tactical errors, or positional weaknesses that led to these mistakes."
    )
    
    user_message = (
        "Here are the flagged moves with their details:\n"
        f"{move_details}\n"
        "Please provide a concise summary of the recurring patterns observed."
    )

    return [
        {"role": "system", "content": system_message},
        {"role": "user", "content": user_message}
    ]

def generate_summary(flagged_moves):
    """
    Generates a summary of flagged moves using call_nemotron.
    """
    if not flagged_moves:
        return "no significant mistakes found"

    messages = build_summary_prompt(flagged_moves)
    summary = call_nemotron(messages)
    return summary
