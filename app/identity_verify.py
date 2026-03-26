import json
from typing import Optional, List, Annotated
from typing_extensions import TypedDict
import operator

from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from langgraph.graph import StateGraph, START, END

from core.redis_client import redis_client
from database import kyc_db

SESSION_TTL = 3600

# -----------------------------------------
# Step definitions
# -----------------------------------------
STEP_ORDER = ["pan_upload", "aadhaar_upload", "selfie_upload"]

STEP_PROMPTS = {
    "pan_upload": "📄 Please upload your **PAN Card** image.\n\nAccepted formats: JPG, PNG, or PDF.",
    "aadhaar_upload": "🪪 Please upload your **Aadhaar Card** image.\n\nAccepted formats: JPG, PNG, or PDF.",
    "selfie_upload": "📸 Please upload a **passport-size photo of yourself** (the same face as on your Aadhaar/PAN).\n\nAccepted formats: JPG or PNG.",
}

# Maps each step to the backend upload endpoint the frontend should call
STEP_UPLOAD_ENDPOINTS = {
    "pan_upload": "/upload-pan",
    "aadhaar_upload": "/upload-aadhaar",
    "selfie_upload": "/upload-selfie",
}


# -----------------------------------------
# State
# -----------------------------------------
class VerificationState(TypedDict):
    messages: Annotated[List[BaseMessage], operator.add]
    current_step: Optional[str]
    verification_data: dict          # {pan: {verified, checks}, aadhaar: {...}, face: {...}}
    verification_complete: Optional[bool]
    temp_input: Optional[str]


# -----------------------------------------
# Helpers
# -----------------------------------------
def calculate_progress(data):
    """Progress based on how many of the 3 steps have verification results."""
    completed = 0
    for key in ["pan", "aadhaar", "face"]:
        if data.get(key, {}).get("verified") is not None:
            completed += 1
    return int((completed / 3) * 100)


def get_key(session_id):
    return f"identity_verification:{session_id}"


# -----------------------------------------
# Redis Session
# -----------------------------------------
async def get_session(session_id) -> VerificationState:
    data = await redis_client.get(get_key(session_id))
    if data:
        parsed = json.loads(data)
        return {
            "messages": [
                HumanMessage(content=m["content"]) if m["type"] == "user" else AIMessage(content=m["content"])
                for m in parsed["messages"]
            ],
            "current_step": parsed.get("current_step"),
            "verification_data": parsed.get("verification_data", {}),
            "verification_complete": False,
            "temp_input": None,
        }

    return {
        "messages": [],
        "current_step": None,
        "verification_data": {},
        "verification_complete": False,
        "temp_input": None,
    }


async def save_session(session_id, state: VerificationState):
    payload = {
        "messages": [
            {"type": "user" if isinstance(m, HumanMessage) else "ai", "content": m.content}
            for m in state["messages"]
        ],
        "current_step": state.get("current_step"),
        "verification_data": state.get("verification_data", {}),
    }
    await redis_client.set(get_key(session_id), json.dumps(payload), ex=SESSION_TTL)


# -----------------------------------------
# Nodes
# -----------------------------------------
def input_node(state: VerificationState):
    """Read user input and initialize step if needed."""
    if not state["messages"]:
        return {}

    user_input = state["messages"][-1].content.strip()
    current_step = state.get("current_step")

    # First invocation — start at pan_upload
    if not current_step:
        return {
            "current_step": STEP_ORDER[0],
            "temp_input": user_input,
        }

    return {"temp_input": user_input}


def verification_check_node(state: VerificationState):
    """After the frontend uploads a file and sends 'uploaded', check MongoDB
    for the verification result of the current step."""
    current_step = state.get("current_step")
    user_input = (state.get("temp_input") or "").lower()
    data = dict(state.get("verification_data", {}))

    if not current_step:
        return {"verification_data": data}

    # The frontend sends "uploaded" after successfully calling the upload endpoint.
    # We also accept "uploaded_success" or messages containing "uploaded".
    if "uploaded" not in user_input:
        # User typed something instead of uploading — remind them to upload
        return {"verification_data": data}

    return {"verification_data": data}


def response_node(state: VerificationState):
    """Generate the next prompt or completion message."""
    current_step = state.get("current_step")
    user_input = (state.get("temp_input") or "").lower()
    data = dict(state.get("verification_data", {}))

    # If user didn't upload (typed text instead), re-prompt
    if current_step and "uploaded" not in user_input:
        msg = f"Please use the upload button to submit your document.\n\n{STEP_PROMPTS.get(current_step, '')}"
        return {"messages": [AIMessage(content=msg)]}

    # Check what step we just completed and look at the upload result
    # The frontend sends "uploaded:success" or "uploaded:failed:reason"
    upload_success = "uploaded:success" in user_input or user_input == "uploaded"
    upload_failed = "uploaded:failed" in user_input

    if upload_failed:
        # Extract error reason if provided
        parts = user_input.split(":", 2)
        reason = parts[2] if len(parts) > 2 else "verification failed"

        error_messages = {
            "pan_upload": f"❌ PAN verification failed: {reason}. Please upload a clear image of your PAN card and try again.",
            "aadhaar_upload": f"❌ Aadhaar verification failed: {reason}. Please upload a clear image of your Aadhaar card and try again.",
            "selfie_upload": f"❌ Face verification failed: {reason}. Please upload a clear, well-lit photo of your face and try again.",
        }
        msg = error_messages.get(current_step, f"❌ Verification failed: {reason}. Please try again.")
        return {"messages": [AIMessage(content=msg)]}

    # Upload succeeded — move to next step
    if upload_success or user_input == "uploaded":
        success_messages = {
            "pan_upload": "✅ PAN Card verified successfully!",
            "aadhaar_upload": "✅ Aadhaar Card verified successfully!",
            "selfie_upload": "✅ Face verification successful! Your identity has been matched.",
        }

        current_index = STEP_ORDER.index(current_step)
        success_msg = success_messages.get(current_step, "✅ Verified!")

        # Check if there's a next step
        if current_index + 1 < len(STEP_ORDER):
            next_step = STEP_ORDER[current_index + 1]
            next_prompt = STEP_PROMPTS[next_step]
            msg = f"{success_msg}\n\n{next_prompt}"
            return {
                "current_step": next_step,
                "messages": [AIMessage(content=msg)],
            }
        else:
            # All steps done
            msg = f"{success_msg}\n\n🎉 **Identity Verification Complete!**\n\nAll your documents have been verified successfully. Your KYC process is now complete."
            return {
                "current_step": None,
                "verification_complete": True,
                "messages": [AIMessage(content=msg)],
            }

    # Default: prompt for current step
    msg = STEP_PROMPTS.get(current_step, "Please upload the required document.")
    return {"messages": [AIMessage(content=msg)]}


# -----------------------------------------
# Graph
# -----------------------------------------
workflow = StateGraph(VerificationState)
workflow.add_node("input", input_node)
workflow.add_node("verify_check", verification_check_node)
workflow.add_node("response", response_node)

workflow.add_edge(START, "input")
workflow.add_edge("input", "verify_check")
workflow.add_edge("verify_check", "response")
workflow.add_edge("response", END)

app = workflow.compile()


# -----------------------------------------
# Main Run
# -----------------------------------------
async def run(session_id: str, user_input: str):
    state = await get_session(session_id)

    if user_input.strip():
        state["messages"].append(HumanMessage(content=user_input))

    new_state = await app.ainvoke(state)
    await save_session(session_id, new_state)

    ai_msg = new_state["messages"][-1].content
    data = new_state.get("verification_data", {})
    current_step = new_state.get("current_step")

    progress = calculate_progress(data)

    # Determine what input type the frontend should show
    input_type = "file_upload" if current_step else "text"

    # Determine the upload endpoint for the frontend
    upload_endpoint = STEP_UPLOAD_ENDPOINTS.get(current_step) if current_step else None

    if new_state.get("verification_complete"):
        await redis_client.delete(get_key(session_id))
        return {
            "message": ai_msg,
            "progress": 100,
            "completed": True,
            "input_type": "text",
            "step": "identity_verification",
            "upload_endpoint": None,
        }

    return {
        "message": ai_msg,
        "progress": progress,
        "completed": False,
        "input_type": input_type,
        "step": "identity_verification",
        "upload_endpoint": upload_endpoint,
    }
