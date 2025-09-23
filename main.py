from flask import Flask, request, jsonify
import requests
import os
from duckduckgo_search import DDGS
import json
from datetime import datetime

app = Flask(__name__)

# Environment variables for API keys
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY",
                               "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")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "meta-llama/llama-3.3-70b-instruct:free"


def search_fitness_info(query, max_results=5):
    """
    Search for fitness-related information using DuckDuckGo
    """
    try:
        with DDGS() as ddgs:
            # Search for relevant fitness information
            search_results = list(ddgs.text(
                keywords=f"fitness health {query}",
                max_results=max_results,
                safesearch='moderate',
                timelimit='y'  # Last year for recent information
            ))

            # Format search results into readable context
            context = []
            for i, result in enumerate(search_results, 1):
                context.append(f"""
Source {i}:
Title: {result.get('title', 'N/A')}
URL: {result.get('href', 'N/A')}
Content: {result.get('body', 'N/A')[:300]}...
""")

            return "\n".join(context) if context else "No relevant search results found."

    except Exception as e:
        print(f"Search error: {e}")
        return f"Search unavailable: {str(e)}"


def should_search(user_message):
    """
    Determine if the user message requires current information search
    """
    search_keywords = [
        'latest', 'recent', 'new', 'current', 'trending', 'update',
        'studies show', 'research', 'news', 'breakthrough', '2024', '2025',
        'what do experts say', 'current recommendations', 'search the web', 'search', 'more information'
    ]

    message_lower = user_message.lower()
    return any(keyword in message_lower for keyword in search_keywords)


@app.route("/fitness-trainer", methods=["POST"])
def fitness_trainer():
    try:
        data = request.get_json()
        user_message = data.get("message", "")
        enable_search = data.get("enable_search", True)  # Allow users to disable search

        if not user_message:
            return jsonify({"error": "Message is required"}), 400

        # Determine if search is needed
        search_context = ""
        search_used = False

        if enable_search and should_search(user_message):
            print(f"Searching for: {user_message}")
            search_context = search_fitness_info(user_message)
            search_used = True

        # Enhanced system prompt with RAG capabilities
        system_prompt = """You are an AI personal fitness and health trainer designed to provide helpful, informative, and supportive guidance to users on their wellness journey. Your role is to motivate, educate, and assist users in achieving their fitness and health goals safely and effectively.

CORE PRINCIPLES:

Safety First: Always prioritize user safety over achieving goals quickly. Recommend users consult healthcare professionals before starting new exercise programs, especially if they have medical conditions, injuries, or haven't exercised in a long time. Never provide medical diagnoses or treatments. Recognize when issues are beyond fitness scope and refer to appropriate professionals. Emphasize proper form and technique to prevent injuries. Encourage rest and recovery as essential components of fitness.

Evidence-Based Approach: Base recommendations on established exercise science and nutrition principles. When current search results are provided, incorporate this information while maintaining critical evaluation. Cite reputable sources when providing specific claims about fitness or nutrition. Acknowledge when information is general guidance vs. personalized advice. Stay updated on current research while avoiding fitness fads or unproven methods.

RAG Integration: When search results are provided, use them to enhance your responses with current information. Always evaluate the credibility of search results and cross-reference with established knowledge. Mention when you're incorporating recent findings or current trends. If search results conflict with established science, prioritize evidence-based approaches while acknowledging the new information.

KEY RESPONSIBILITIES:

Workout Planning and Exercise Guidance: Design balanced workout routines incorporating cardiovascular, strength, flexibility, and mobility training. Provide clear exercise instructions with emphasis on proper form. Suggest modifications for different fitness levels and physical limitations. Recommend appropriate progression and regression strategies. Explain the purpose and benefits of different exercises and training methods.

Nutritional Guidance: Provide general nutrition education based on established dietary guidelines. Help users understand macronutrients, micronutrients, and their roles. Suggest healthy eating patterns rather than restrictive diets. Emphasize the importance of adequate hydration. IMPORTANT: Refer users to registered dietitians for specific meal plans, medical nutrition therapy, or complex dietary needs.

Current Information Integration: When search results are available, incorporate recent findings, trends, and updates in fitness and nutrition science. Evaluate the credibility of sources and highlight when information is particularly current or represents emerging research.

IMPORTANT LIMITATIONS AND BOUNDARIES:

Medical Boundaries: Never diagnose medical conditions or provide medical treatment advice. Recognize symptoms that require medical attention. Acknowledge when issues may be related to underlying health conditions. Emphasize that fitness advice complements but doesn't replace medical care.

Information Verification: When using search results, always maintain critical thinking. Prioritize information from reputable sources like peer-reviewed studies, certified professionals, and established health organizations. Flag when information seems contradictory or requires professional verification.

When answering, keep responses concise (under 5 bullet points or 150 words). Do not cut off mid-sentence."""

        # Build messages array
        messages = [{"role": "system", "content": system_prompt}]

        # Add search context if available
        if search_context and search_used:
            messages.append({
                "role": "system",
                "content": f"CURRENT SEARCH RESULTS (Use this information to enhance your response):\n{search_context}\n\nPlease incorporate relevant information from these search results while maintaining your evidence-based approach."
            })

        messages.append({"role": "user", "content": user_message})

        # Payload to OpenRouter
        payload = {
            "model": MODEL,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 1000
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENROUTER_API_KEY}"
        }

        response = requests.post(OPENROUTER_URL, headers=headers, json=payload)

        if response.status_code != 200:
            return jsonify({
                "error": "Failed to connect to OpenRouter",
                "details": response.text,
                "status_code": response.status_code
            }), 500

        result = response.json()

        if "choices" not in result or not result["choices"]:
            return jsonify({
                "error": "Invalid response from OpenRouter",
                "details": result
            }), 500

        reply = result["choices"][0]["message"]["content"]

        return jsonify({
            "user_message": user_message,
            "ai_reply": reply,
            "search_used": search_used,
            "timestamp": datetime.now().isoformat(),
            "model_used": MODEL
        })

    except Exception as e:
        return jsonify({
            "error": str(e),
            "type": type(e).__name__
        }), 500


@app.route("/search", methods=["POST"])
def manual_search():
    """
    Manual search endpoint for testing DuckDuckGo integration
    """
    try:
        data = request.get_json()
        query = data.get("query", "")

        if not query:
            return jsonify({"error": "Query is required"}), 400

        search_results = search_fitness_info(query)

        return jsonify({
            "query": query,
            "search_results": search_results,
            "timestamp": datetime.now().isoformat()
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/", methods=["GET"])
def index():
    return jsonify({
        "message": "AI Fitness Trainer API with RAG is running",
        "features": [
            "Fitness training advice",
            "DuckDuckGo search integration",
            "Real-time information retrieval",
            "Evidence-based recommendations"
        ],
        "endpoints": {
            "/fitness-trainer": "POST - Main fitness trainer endpoint",
            "/search": "POST - Manual search testing",
            "/": "GET - API status"
        }
    })


@app.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint"""
    try:
        # Test search functionality
        test_search = search_fitness_info("fitness", max_results=1)
        search_working = "No relevant search results found." not in test_search

        return jsonify({
            "status": "healthy",
            "search_enabled": search_working,
            "model": MODEL,
            "timestamp": datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            "status": "degraded",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }), 503


if __name__ == "__main__":
    # Test search on startup
    try:
        test_result = search_fitness_info("fitness test", max_results=1)
        print("✅ DuckDuckGo search is working")
        print(f"Test result: {test_result[:100]}...")
    except Exception as e:
        print(f"⚠️ DuckDuckGo search test failed: {e}")

    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)