import json
import os
import warnings
from collections import defaultdict
from pathlib import Path

import googleapiclient.discovery
import requests
from gspread.exceptions import APIError
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from django.contrib.auth import logout as django_logout
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from google_auth_oauthlib.flow import Flow
from oauthlib.oauth2 import OAuth2Error
from oauthlib.oauth2.rfc6749.errors import InvalidGrantError

from constants import OauthConstants
from tracker.google_sheet_client_manager import GoogleSheetClientManager
from tracker.helpers import LoggingMixin, AmiiboRemoteFetchMixin, AmiiboLocalFetchMixin
from tracker.service_domain import AmiiboService, GoogleSheetConfigManager
from tracker.exceptions import (
    GoogleSheetsError,
    SpreadsheetNotFoundError,
    SpreadsheetPermissionError,
    ServiceUnavailableError,
    RateLimitError,
    QuotaExceededError,
    InvalidCredentialsError,
    NetworkError,
)

os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")


BLOG_POSTS = [
    {
        "slug": "how-it-works",
        "title": "How it Works",
        "date": "2026-02-10",
        "excerpt": "Learn about the NFC technology that powers Amiibo figurines and how they communicate with Nintendo consoles.",
        "content": """
<h2>What are Amiibo?</h2>
<p>Amiibo work by using embedded NFC (Near Field Communication) technology in figurines or cards to wirelessly communicate with compatible Nintendo consoles (Switch, Wii U, 3DS), unlocking digital content like new characters, special items, or game modes by tapping them to the console's NFC reader, effectively acting as physical DLC. The specific effect depends on the game, ranging from boosting a character's abilities in Super Smash Bros. to unlocking unique gear in Zelda or inviting villagers in Animal Crossing.</p>

<h2>How the Technology Works</h2>

<h3>NFC Chip</h3>
<p>Each amiibo figure or card contains a small NFC chip that stores data.</p>

<h3>Scanning</h3>
<p>When tapped against the NFC touchpoint on a Nintendo Switch (right Joy-Con, Pro Controller, or Switch Lite's right stick), the console reads the chip's data.</p>

<h3>In-Game Activation</h3>
<p>The game interprets the data to trigger an event, such as:</p>
<ul>
    <li><strong>Unlocking Content:</strong> Getting new weapons, outfits, or modes.</li>
    <li><strong>Character Interaction:</strong> Making an amiibo character appear as a fighter, support, or partner.</li>
    <li><strong>Saving Data:</strong> In some games, they save data (like a character's level or outfit) back to the figure.</li>
</ul>

<h2>Examples of Use</h2>
<ul>
    <li><strong>The Legend of Zelda:</strong> Scan for rare materials, weapons, or unique paraglider fabrics.</li>
    <li><strong>Super Smash Bros.:</strong> Train your amiibo as a fighter or a formidable foe.</li>
    <li><strong>Animal Crossing:</strong> Invite specific villagers to your campsite to live on your island or get special items.</li>
    <li><strong>Mario Party Superstars:</strong> Use Mario-themed amiibo for custom game boards or bonuses.</li>
</ul>
""",
    },
    {
        "slug": "pronunciation",
        "title": "How to Pronounce Amiibo",
        "date": "2026-02-10",
        "excerpt": 'Ever wondered how to correctly pronounce "amiibo"? Learn the proper pronunciation and what the name actually means.',
        "content": """
<h2>The Correct Pronunciation</h2>
<p>The word "amiibo" is pronounced:</p>
<p style="font-size: 2rem; text-align: center; margin: 2rem 0; color: var(--saffron); font-weight: 600;">uh · mee · bow</p>
<p>Break it down into three syllables: "ah-MEE-bo". The emphasis is on the middle syllable "MEE".</p>

<h2>Origin of the Name</h2>
<p>The name "amiibo" is a blend of two concepts:</p>
<ul>
    <li><strong>Ami:</strong> The Japanese word for "friend" (友, pronounced "tomo" but using the French "ami" for international appeal)</li>
    <li><strong>Aibo:</strong> A reference to Sony's robotic companion dog, suggesting a friendly, interactive companion</li>
</ul>

<h2>Common Mispronunciations</h2>
<p>Many people initially mispronounce amiibo as:</p>
<ul>
    <li>"uh-MEE-boh" (too harsh on the last syllable)</li>
    <li>"AM-ee-boh" (emphasis on wrong syllable)</li>
    <li>"ah-mee-BOH" (emphasis on last syllable instead of middle)</li>
</ul>

<h2>Why It Matters</h2>
<p>While there's no wrong way to enjoy your collection, knowing the correct pronunciation can help when:</p>
<ul>
    <li>Discussing amiibo with other collectors</li>
    <li>Shopping at game stores</li>
    <li>Watching Nintendo Direct presentations</li>
    <li>Participating in online communities</li>
</ul>

<p>Now you can confidently say "amiibo" like a true collector!</p>
""",
    },
    {
        "slug": "number-released",
        "title": "All Released Amiibo",
        "date": "2026-02-10",
        "excerpt": "A complete, always up-to-date list of every amiibo ever released, sorted by newest to oldest.",
        "content": "dynamic",  # Special marker for dynamic content
    },
    {
        "slug": "history-of-amiibo",
        "title": "History of Amiibo",
        "date": "2026-02-10",
        "excerpt": "Explore the journey of Amiibo from its 2014 launch to becoming Nintendo's beloved toys-to-life platform.",
        "content": """
<h2>Pre-Announcement: March 2014</h2>
<p>The story of amiibo began in March 2014, when Nintendo revealed during their financial briefing that they were developing an NFC (Near Field Communication) figurine platform, codenamed "NFP" which stood for either "Nintendo Figure Platform" or "NFC Featured Platform." This announcement hinted at Nintendo's entry into the growing toys-to-life market.</p>

<h2>Official Announcement: E3 2014</h2>
<p>On June 10, 2014, during Nintendo's E3 presentation, the company made its official announcement of "amiibo" - its answer to competing toys-to-life platforms like Activision's Skylanders (launched 2011), Disney Infinity (launched 2013), and what would later be LEGO Dimensions. Nintendo of America chief Reggie Fils-Aimé revealed that amiibo figures would be priced comparably to these competitors, positioning Nintendo firmly in the toys-to-life market.</p>

<h2>Launch: November-December 2014</h2>
<p>Amiibo officially launched alongside Super Smash Bros. for Wii U with staggered regional releases:</p>
<ul>
    <li><strong>North America:</strong> November 21, 2014</li>
    <li><strong>Europe:</strong> November 28, 2014</li>
    <li><strong>Japan:</strong> December 6, 2014</li>
</ul>
<p>The first wave featured 12 characters from the Super Smash Bros. series, each beautifully sculpted figure containing an NFC chip that could interact with compatible games on Wii U and 3DS (with NFC reader adapter).</p>

<h2>The Technology</h2>
<p>Using Near Field Communication (NFC) technology, amiibo figures could be tapped against compatible Nintendo consoles to unlock special content, characters, or gameplay features. This innovative approach bridged the gap between physical collectibles and digital gaming experiences. Unlike competitors, amiibo figures could work across multiple games, with each game developer choosing how to implement amiibo functionality.</p>

<h2>The "Holy Trinity" Crisis: Late 2014-2015</h2>
<p>Within weeks of launch, amiibo faced an unexpected crisis. Three figures—Marth (Fire Emblem), Villager (Animal Crossing), and Wii Fit Trainer—quickly sold out across retailers and became known as the "Holy Trinity" or "unicorns" among collectors. In December 2014, Nintendo announced that some figures were "unlikely to get second shipments" due to shelf space constraints.</p>

<p>The shortage became legendary:</p>
<ul>
    <li>Toys "R" Us announced they would no longer stock the Holy Trinity under their current SKUs</li>
    <li>GameStop confirmed these three figures were "no longer in the system country-wide"</li>
    <li>Marth figures routinely sold for $130+ on secondary markets (compared to $12.99-$15.99 MSRP)</li>
    <li>Villager figures approached similar resale prices</li>
    <li>Nintendo's messaging was inconsistent—first claiming discontinuation, then denying it, creating confusion</li>
</ul>

<p>This scarcity created a passionate collector community, with enthusiasts camping outside stores for new releases and tracking restocks online. The "Amiibogeddon" shortage dominated gaming news throughout 2015.</p>

<h2>Evolution and Expansion</h2>
<p>Over the years, amiibo evolved beyond traditional figures:</p>
<ul>
    <li><strong>Amiibo Cards:</strong> More affordable, portable alternatives featuring the same NFC functionality, launched with Animal Crossing series</li>
    <li><strong>Various Series:</strong> Expanded from Super Smash Bros. to include Animal Crossing, The Legend of Zelda, Splatoon, Super Mario, Metroid, Pokémon, and many more franchises</li>
    <li><strong>Special Editions:</strong> Limited edition designs, exclusive colors, and commemorative releases (like gold and silver variants)</li>
    <li><strong>Cross-Platform Support:</strong> Compatibility expanded from Wii U to 3DS (with NFC adapter) and Nintendo Switch (with built-in NFC support)</li>
    <li><strong>Yarn and Pixel Variants:</strong> Unique materials and styles like Yarn Yoshi figures and pixel art designs</li>
</ul>

<h2>Massive Success: 77 Million and Counting</h2>
<p>As of September 30, 2022, Nintendo had shipped over 77 million amiibo figures worldwide, spanning franchises like Mario, Donkey Kong, Splatoon, Super Smash Bros., and more. This remarkable achievement solidified amiibo as one of the most successful toys-to-life platforms ever created.</p>

<h2>Surviving the Toys-to-Life Decline</h2>
<p>While competitors like Disney Infinity (discontinued 2016), LEGO Dimensions (discontinued 2017), and Skylanders (last release 2017) gradually exited the market, amiibo continued thriving. Nintendo's strategy of:</p>
<ul>
    <li>Using beloved first-party characters with built-in fanbases</li>
    <li>Offering optional enhancement rather than required purchases</li>
    <li>Maintaining high-quality figure sculpts appealing to collectors</li>
    <li>Ensuring cross-game compatibility</li>
</ul>
<p>...allowed amiibo to outlast and outperform its competitors.</p>

<h2>Ongoing Platform</h2>
<p>Today, amiibo remains a popular and ongoing platform for Nintendo enthusiasts. New figures continue to be released alongside major game launches, and the library of compatible games keeps growing. Whether you're a dedicated collector or a casual gamer, amiibo offers a unique way to enhance your Nintendo experience and own physical representations of your favorite characters.</p>

<h2>The Legacy</h2>
<p>Amiibo has successfully carved out its place in gaming history as the most enduring toys-to-life platform. From the chaotic "Holy Trinity" shortage to shipping 77+ million units globally, amiibo proved that combining quality figures, beloved characters, and meaningful (but optional) gameplay integration creates lasting value. Nintendo's amiibo stands as a testament to how physical collectibles can meaningfully enhance digital entertainment without becoming a required expense—a balance that helped it survive when competitors could not.</p>
""",
    },
]


def is_rate_limit_error(error: Exception) -> bool:
    return isinstance(error, APIError) and getattr(error, "code", None) == 429


def retry_after_seconds(error: APIError, default: int = 30) -> int:
    try:
        return int(error.response.headers.get("Retry-After", default))
    except Exception:
        return default


def rate_limit_json_response(error: APIError):
    wait_seconds = retry_after_seconds(error)
    return JsonResponse(
        {
            "status": "rate_limited",
            "message": "Google Sheets rate limit reached. Please wait before trying again.",
            "retry_after": wait_seconds,
        },
        status=429,
    )


def build_sheet_client_manager(request, creds_json=None) -> GoogleSheetClientManager:
    return GoogleSheetClientManager(
        creds_json=(
            creds_json if creds_json is not None else request.session.get("credentials")
        ),
        spreadsheet_id=request.session.get("spreadsheet_id"),
    )


def ensure_spreadsheet_session(request, manager: GoogleSheetClientManager):
    if not hasattr(manager, "spreadsheet"):
        return None

    spreadsheet = manager.spreadsheet
    if getattr(manager, "spreadsheet_id", None):
        request.session["spreadsheet_id"] = manager.spreadsheet_id
    return spreadsheet


def credentials_to_dict(creds: Credentials):
    return {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
        "expiry": creds.expiry.isoformat() if creds.expiry else None,
    }


def get_active_credentials_json(request, log_action=None):
    creds_json = request.session.get("credentials")
    if not creds_json:
        return None

    try:
        credentials = Credentials.from_authorized_user_info(
            creds_json, OauthConstants.SCOPES
        )
    except Exception as error:
        if log_action:
            log_action(
                "credentials-parse-failed",
                request,
                level="warning",
                error=str(error),
            )
        request.session.pop("credentials", None)
        return None

    if credentials.expired:
        if not credentials.refresh_token:
            if log_action:
                log_action(
                    "credentials-expired",
                    request,
                    level="warning",
                )
            request.session.pop("credentials", None)
            return None

        try:
            credentials.refresh(GoogleAuthRequest())
            request.session["credentials"] = credentials_to_dict(credentials)
        except Exception as error:
            if log_action:
                log_action(
                    "credential-refresh-failed",
                    request,
                    level="warning",
                    error=str(error),
                )
            request.session.pop("credentials", None)
            return None

    if not credentials.valid:
        if log_action:
            log_action(
                "credentials-invalid",
                request,
                level="warning",
            )
        request.session.pop("credentials", None)
        return None

    return request.session.get("credentials")


def logout_user(request, log_action=None):
    # Capture user info before session is flushed
    user_name = request.session.get("user_name")
    user_email = request.session.get("user_email")

    if log_action:
        log_action(
            "logout-requested", request, user_name=user_name, user_email=user_email
        )

    creds = request.session.get("credentials")
    if creds:
        token = creds.get("token")
        try:
            response = requests.post(
                "https://oauth2.googleapis.com/revoke",
                params={"token": token},
                headers={"content-type": "application/x-www-form-urlencoded"},
            )
            if log_action:
                log_action(
                    "logout-complete",
                    request,
                    status_code=response.status_code,
                    user_name=user_name,
                    user_email=user_email,
                )
        except Exception as e:
            if log_action:
                log_action(
                    "logout-revoke-failed",
                    request,
                    level="error",
                    error=str(e),
                    user_name=user_name,
                    user_email=user_email,
                )

    request.session.flush()
    django_logout(request)


@method_decorator(csrf_exempt, name="dispatch")
class ToggleCollectedView(View, LoggingMixin):
    def post(self, request):
        raw_creds = request.session.get("credentials")
        creds_json = get_active_credentials_json(request, self.log_action)
        if not creds_json:
            if raw_creds:
                creds_json = raw_creds
                self.log_action(
                    "using-stored-credentials",
                    request,
                    level="warning",
                    http_method="POST",
                    endpoint="toggle-collected",
                )
            else:
                self.log_action(
                    "missing-credentials",
                    request,
                    level="warning",
                    http_method="POST",
                    endpoint="toggle-collected",
                )
                return redirect("oauth_login")

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            self.log_action(
                "invalid-payload",
                request,
                level="warning",
                http_method="POST",
                endpoint="toggle-collected",
            )
            return JsonResponse(
                {"status": "error", "message": "Invalid JSON payload."}, status=400
            )

        try:
            google_sheet_client_manager = build_sheet_client_manager(
                request, creds_json
            )
            ensure_spreadsheet_session(request, google_sheet_client_manager)
        except GoogleSheetsError as error:
            self.log_error(
                "Google Sheets error during toggle: %s",
                str(error),
                user_name=request.session.get("user_name"),
                user_email=request.session.get("user_email"),
            )
            return JsonResponse(
                {
                    "status": "error",
                    "message": error.user_message,
                    "action_required": error.action_required,
                },
                status=503,
            )

        amiibo_id = data.get("amiibo_id")
        action = data.get("action")

        if not amiibo_id or action not in {"collect", "uncollect"}:
            self.log_action(
                "missing-parameters",
                request,
                level="warning",
                http_method="POST",
                endpoint="toggle-collected",
                amiibo_id=amiibo_id,
                action=action,
            )
            return JsonResponse(
                {
                    "status": "error",
                    "message": "Both amiibo_id and a valid action are required.",
                },
                status=400,
            )

        try:
            service = AmiiboService(
                google_sheet_client_manager=google_sheet_client_manager
            )
            success = service.toggle_collected(amiibo_id, action)

            if not success:
                self.log_action(
                    "amiibo-not-found",
                    request,
                    level="warning",
                    amiibo_id=amiibo_id,
                    action=action,
                )
                return JsonResponse({"status": "not found"}, status=404)

            self.log_action(
                "collection-updated",
                request,
                amiibo_id=amiibo_id,
                action=action,
            )
            return JsonResponse({"status": "success"})

        except GoogleSheetsError as error:
            self.log_error(
                "Google Sheets error: %s",
                str(error),
                user_name=request.session.get("user_name"),
                user_email=request.session.get("user_email"),
            )
            status_code = 429 if isinstance(error, RateLimitError) else 503
            return JsonResponse(
                {
                    "status": "error",
                    "message": error.user_message,
                    "action_required": error.action_required,
                    "retry_after": getattr(error, "retry_after", None),
                },
                status=status_code,
            )

        except APIError as error:
            if is_rate_limit_error(error):
                self.log_action(
                    "rate-limited",
                    request,
                    level="warning",
                    amiibo_id=amiibo_id,
                    action=action,
                    retry_after=retry_after_seconds(error),
                )
                return rate_limit_json_response(error)
            return JsonResponse(
                {"status": "error", "message": "Unexpected Google API error."},
                status=500,
            )

        except Exception as e:
            self.log_action(
                "toggle-error",
                request,
                level="error",
                amiibo_id=amiibo_id,
                action=action,
                error=str(e),
            )
            return JsonResponse({"status": "error", "message": str(e)}, status=500)

    def get(self, request):
        return JsonResponse({"status": "invalid method"}, status=400)


class OAuthView(View, LoggingMixin):
    def get(self, request):
        creds_json = get_active_credentials_json(request, self.log_action)
        if creds_json:
            return redirect("amiibo_list")

        logout_user(request, self.log_action)

        flow = Flow.from_client_secrets_file(
            GoogleSheetClientManager.client_secret_path(),
            scopes=OauthConstants.SCOPES,
            redirect_uri=OauthConstants.REDIRECT_URI,
            autogenerate_code_verifier=True,
        )
        auth_url, state = flow.authorization_url(
            access_type="offline",
            include_granted_scopes="true",
            prompt="consent",
        )

        request.session["oauth_state"] = state
        request.session["oauth_code_verifier"] = flow.code_verifier

        return redirect(auth_url)


class OAuthCallbackView(View, LoggingMixin):
    def get(self, request):
        request_state = request.GET.get("state")
        oauth_state = request.session.get("oauth_state")
        oauth_code_verifier = request.session.get("oauth_code_verifier")
        error = request.GET.get("error")
        authorization_code = request.GET.get("code")

        # If Google returned an explicit error or no auth code, send the user back
        # through the OAuth login flow instead of raising an exception.
        if error or not authorization_code:
            request.session.pop("oauth_state", None)
            request.session.pop("oauth_code_verifier", None)
            return redirect("oauth_login")

        # If the state is missing from the session (e.g., a new browser session) try to
        # recover using the callback payload before forcing users through a second
        # authorization prompt. Still require the provided state to match what we last
        # issued when available to avoid unnecessary re-auth redirects.
        if oauth_state and request_state and request_state != oauth_state:
            request.session.pop("oauth_state", None)
            request.session.pop("oauth_code_verifier", None)
            return redirect("oauth_login")

        if not oauth_state:
            if not request_state:
                request.session.pop("oauth_code_verifier", None)
                return redirect("oauth_login")
            oauth_state = request_state

        if not oauth_code_verifier:
            request.session.pop("oauth_state", None)
            request.session.pop("oauth_code_verifier", None)
            return redirect("oauth_login")

        flow = Flow.from_client_secrets_file(
            GoogleSheetClientManager.client_secret_path(),
            scopes=OauthConstants.SCOPES,
            redirect_uri=OauthConstants.REDIRECT_URI,
            state=oauth_state,
            code_verifier=oauth_code_verifier,
            autogenerate_code_verifier=False,
        )

        try:
            flow.fetch_token(authorization_response=request.build_absolute_uri())
        except Warning as scope_warning:
            self.log_action(
                "scope-warning", request, level="warning", warning=str(scope_warning)
            )

            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    flow.fetch_token(
                        authorization_response=request.build_absolute_uri()
                    )
            except (InvalidGrantError, OAuth2Error, Warning):
                request.session.pop("oauth_state", None)
                request.session.pop("oauth_code_verifier", None)
                return redirect("oauth_login")

        except (InvalidGrantError, OAuth2Error):
            request.session.pop("oauth_state", None)
            request.session.pop("oauth_code_verifier", None)
            return redirect("oauth_login")

        credentials = flow.credentials

        required_scopes = set(OauthConstants.SCOPES)
        granted_scopes = set(credentials.scopes or [])

        if not required_scopes.issubset(granted_scopes):
            self.log_action(
                "missing-scopes",
                request,
                level="warning",
                required_scopes=list(required_scopes),
                granted_scopes=list(granted_scopes),
            )

            request.session.pop("oauth_state", None)
            request.session.pop("oauth_code_verifier", None)
            request.session.pop("credentials", None)
            request.session.pop("user_name", None)
            request.session.pop("user_email", None)

            return redirect("oauth_login")

        # Clear any stale session data before persisting new account details
        request.session.pop("credentials", None)
        request.session.pop("user_name", None)
        request.session.pop("user_email", None)

        request.session.pop("oauth_state", None)
        request.session.pop("oauth_code_verifier", None)
        request.session["credentials"] = credentials_to_dict(credentials)

        user_service = googleapiclient.discovery.build(
            "oauth2", "v2", credentials=credentials
        )
        user_info = user_service.userinfo().get().execute()

        request.session["user_name"] = user_info.get("name")
        request.session["user_email"] = user_info.get("email")

        try:
            manager = build_sheet_client_manager(request)
            ensure_spreadsheet_session(request, manager)
        except Exception as error:
            self.log_action(
                "spreadsheet-init-failed",
                request,
                level="error",
                error=str(error),
            )
            raise

        self.log_action(
            "login-success",
            request,
            user_name=request.session.get("user_name"),
            user_email=request.session.get("user_email"),
        )

        return redirect("amiibo_list")


class LogoutView(View, LoggingMixin):
    def get(self, request):
        logout_user(request, self.log_action)
        return redirect("index")


class AmiiboListView(View, LoggingMixin, AmiiboRemoteFetchMixin):
    def _render_error_view(self, request, error, user_name):
        """
        Render the amiibo view with an error modal displayed.
        Falls back to displaying amiibos from the API in read-only mode.

        Args:
            request: The HTTP request
            error: The GoogleSheetsError exception
            user_name: The user's name

        Returns:
            Rendered template with error information and fallback data
        """
        self.log_error(
            "Google Sheets error: %s",
            str(error),
            user_name=request.session.get("user_name"),
            user_email=request.session.get("user_email"),
        )

        # Try to fetch amiibos from the remote API as fallback
        try:
            amiibos = self._fetch_remote_amiibos()
            available_types = sorted(
                {amiibo.get("type", "") for amiibo in amiibos if amiibo.get("type")}
            )

            # Mark all as uncollected since we can't read from sheets
            for amiibo in amiibos:
                amiibo["collected"] = False
                amiibo["display_release"] = AmiiboService._format_release_date(
                    amiibo.get("release")
                )

            # Sort and group amiibos
            sorted_amiibos = sorted(
                amiibos, key=lambda x: (x.get("amiiboSeries", ""), x.get("name", ""))
            )
            grouped_amiibos = defaultdict(list)
            for amiibo in sorted_amiibos:
                grouped_amiibos[amiibo.get("amiiboSeries", "Unknown")].append(amiibo)

            enriched_groups = []
            for series, amiibo_list in grouped_amiibos.items():
                enriched_groups.append(
                    {
                        "series": series,
                        "list": amiibo_list,
                        "collected_count": 0,
                        "total_count": len(amiibo_list),
                    }
                )

        except Exception as fetch_error:
            self.log_warning(
                "Failed to fetch fallback amiibos: %s",
                str(fetch_error),
                user_name=request.session.get("user_name"),
                user_email=request.session.get("user_email"),
            )
            sorted_amiibos = []
            available_types = []
            enriched_groups = []

        # Prepare context for error display
        context = {
            "amiibos": sorted_amiibos,
            "dark_mode": False,
            "user_name": user_name,
            "grouped_amiibos": enriched_groups,
            "amiibo_types": [
                {"name": amiibo_type, "ignored": False}
                for amiibo_type in available_types
            ],
            "rate_limited": False,
            "rate_limit_wait_seconds": 0,
            "error": {
                "message": error.user_message,
                "action_required": error.action_required,
                "is_retryable": error.is_retryable,
            },
        }

        # Special handling for rate limit errors
        if isinstance(error, RateLimitError):
            context["rate_limited"] = True
            context["rate_limit_wait_seconds"] = error.retry_after

        return render(request, "tracker/amiibos.html", context)

    def get(self, request):
        creds_json = get_active_credentials_json(request, self.log_action)
        if not creds_json:
            return redirect("oauth_login")

        user_name = request.session.get("user_name", "User")

        try:
            google_sheet_client_manager = build_sheet_client_manager(
                request, creds_json
            )
            ensure_spreadsheet_session(request, google_sheet_client_manager)
        except GoogleSheetsError as error:
            # Handle errors that occur during spreadsheet initialization
            return self._render_error_view(request, error, user_name)
        service = AmiiboService(google_sheet_client_manager=google_sheet_client_manager)
        config = GoogleSheetConfigManager(
            google_sheet_client_manager=google_sheet_client_manager
        )

        try:
            amiibos = service.fetch_amiibos()
            available_types = sorted(
                {amiibo.get("type", "") for amiibo in amiibos if amiibo.get("type")}
            )

            dark_mode = config.is_dark_mode()
            ignored_types = config.get_ignored_types(available_types)
            filtered_amiibos = [
                a for a in amiibos if a.get("type") not in ignored_types
            ]

            service.seed_new_amiibos(filtered_amiibos)
            collected_status = service.get_collected_status()

            for amiibo in filtered_amiibos:
                amiibo_id = amiibo["head"] + amiibo["gameSeries"] + amiibo["tail"]
                amiibo["collected"] = collected_status.get(amiibo_id) == "1"
                amiibo["display_release"] = AmiiboService._format_release_date(
                    amiibo.get("release")
                )

            sorted_amiibos = sorted(
                filtered_amiibos, key=lambda x: (x["amiiboSeries"], x["name"])
            )
            grouped_amiibos = defaultdict(list)
            for amiibo in sorted_amiibos:
                grouped_amiibos[amiibo["amiiboSeries"]].append(amiibo)

            enriched_groups = []
            for series, amiibos in grouped_amiibos.items():
                total = len(amiibos)
                collected = sum(1 for a in amiibos if a["collected"])
                enriched_groups.append(
                    {
                        "series": series,
                        "list": amiibos,
                        "collected_count": collected,
                        "total_count": total,
                    }
                )

            self.log_action(
                "render-collection",
                request,
                total_amiibos=len(sorted_amiibos),
                grouped_series=len(enriched_groups),
                ignored_types=len(ignored_types),
                dark_mode=dark_mode,
            )

            return render(
                request,
                "tracker/amiibos.html",
                {
                    "amiibos": sorted_amiibos,
                    "dark_mode": dark_mode,
                    "user_name": user_name,
                    "grouped_amiibos": enriched_groups,
                    "amiibo_types": [
                        {"name": amiibo_type, "ignored": amiibo_type in ignored_types}
                        for amiibo_type in available_types
                    ],
                    "rate_limited": False,
                    "rate_limit_wait_seconds": 0,
                },
            )

        except GoogleSheetsError as error:
            # Handle our custom exceptions with user-friendly error modal
            return self._render_error_view(request, error, user_name)

        except APIError as error:
            # Handle any remaining APIError exceptions
            if is_rate_limit_error(error):
                # Convert to our custom exception for consistent handling
                rate_limit_error = RateLimitError(
                    retry_after=retry_after_seconds(error)
                )
                return self._render_error_view(request, rate_limit_error, user_name)

            # For other API errors, re-raise to let Django handle them
            self.log_error(
                "Unhandled API error: %s",
                error,
                user_name=request.session.get("user_name"),
                user_email=request.session.get("user_email"),
            )
            raise


@method_decorator(csrf_exempt, name="dispatch")
class ToggleDarkModeView(View, LoggingMixin):
    def post(self, request):
        creds_json = get_active_credentials_json(request, self.log_action)
        if not creds_json:
            self.log_action(
                "missing-credentials",
                request,
                level="warning",
                http_method="POST",
                endpoint="toggle-dark-mode",
            )
            return redirect("oauth_login")

        try:
            google_sheet_client_manager = build_sheet_client_manager(
                request, creds_json
            )
            ensure_spreadsheet_session(request, google_sheet_client_manager)

            data = json.loads(request.body)
            enable_dark = data.get("dark_mode", True)

            config = GoogleSheetConfigManager(
                google_sheet_client_manager=google_sheet_client_manager
            )
            config.set_dark_mode(enable_dark)

            self.log_action(
                "dark-mode-updated",
                request,
                dark_mode=enable_dark,
            )
            return JsonResponse({"status": "success"})

        except GoogleSheetsError as error:
            self.log_error(
                "Google Sheets error during dark mode toggle: %s",
                str(error),
                user_name=request.session.get("user_name"),
                user_email=request.session.get("user_email"),
            )
            status_code = 429 if isinstance(error, RateLimitError) else 503
            return JsonResponse(
                {
                    "status": "error",
                    "message": error.user_message,
                    "action_required": error.action_required,
                    "retry_after": getattr(error, "retry_after", None),
                },
                status=status_code,
            )

        except APIError as error:
            if is_rate_limit_error(error):
                self.log_action(
                    "rate-limited",
                    request,
                    level="warning",
                    endpoint="toggle-dark-mode",
                    retry_after=retry_after_seconds(error),
                )
                return rate_limit_json_response(error)
            return JsonResponse(
                {"status": "error", "message": "Unexpected Google API error."},
                status=500,
            )
        except Exception as e:
            self.log_action(
                "dark-mode-error",
                request,
                level="error",
                endpoint="toggle-dark-mode",
                error=str(e),
            )
            return JsonResponse({"status": "error", "message": str(e)}, status=500)


@method_decorator(csrf_exempt, name="dispatch")
class ToggleTypeFilterView(View, LoggingMixin):
    def post(self, request):
        creds_json = get_active_credentials_json(request, self.log_action)
        if not creds_json:
            self.log_action(
                "missing-credentials",
                request,
                level="warning",
                http_method="POST",
                endpoint="toggle-type-filter",
            )
            return redirect("oauth_login")

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            self.log_action(
                "invalid-payload",
                request,
                level="warning",
                http_method="POST",
                endpoint="toggle-type-filter",
            )
            return JsonResponse(
                {"status": "error", "message": "Invalid JSON payload."}, status=400
            )

        try:
            google_sheet_client_manager = build_sheet_client_manager(
                request, creds_json
            )
            ensure_spreadsheet_session(request, google_sheet_client_manager)
        except GoogleSheetsError as error:
            self.log_error(
                "Google Sheets error during type filter toggle: %s", str(error)
            )
            status_code = 429 if isinstance(error, RateLimitError) else 503
            return JsonResponse(
                {
                    "status": "error",
                    "message": error.user_message,
                    "action_required": error.action_required,
                    "retry_after": getattr(error, "retry_after", None),
                },
                status=status_code,
            )

        amiibo_type = data.get("type")
        ignore = data.get("ignore", True)

        if not amiibo_type:
            self.log_action(
                "missing-parameters",
                request,
                level="warning",
                http_method="POST",
                endpoint="toggle-type-filter",
            )
            return JsonResponse(
                {"status": "error", "message": "Missing type"}, status=400
            )

        try:
            config = GoogleSheetConfigManager(
                google_sheet_client_manager=google_sheet_client_manager
            )
            config.set_ignore_type(amiibo_type, ignore)

            self.log_action(
                "type-filter-updated",
                request,
                amiibo_type=amiibo_type,
                ignore=ignore,
            )
            return JsonResponse({"status": "success"})

        except GoogleSheetsError as error:
            self.log_error(
                "Google Sheets error: %s",
                str(error),
                user_name=request.session.get("user_name"),
                user_email=request.session.get("user_email"),
            )
            status_code = 429 if isinstance(error, RateLimitError) else 503
            return JsonResponse(
                {
                    "status": "error",
                    "message": error.user_message,
                    "action_required": error.action_required,
                    "retry_after": getattr(error, "retry_after", None),
                },
                status=status_code,
            )

        except APIError as error:
            if is_rate_limit_error(error):
                self.log_action(
                    "rate-limited",
                    request,
                    level="warning",
                    endpoint="toggle-type-filter",
                    retry_after=retry_after_seconds(error),
                )
                return rate_limit_json_response(error)
            return JsonResponse(
                {"status": "error", "message": "Unexpected Google API error."},
                status=500,
            )
        except Exception as e:
            self.log_action(
                "type-filter-error",
                request,
                level="error",
                endpoint="toggle-type-filter",
                error=str(e),
            )
            return JsonResponse({"status": "error", "message": str(e)}, status=500)

    def get(self, request):
        return JsonResponse({"status": "invalid method"}, status=400)


class IndexView(View):
    def get(self, request):
        if request.user.is_authenticated:
            return redirect("amiibo_list")
        return render(request, "tracker/index.html")


class DemoView(View):
    def get(self, request):
        return render(request, "tracker/demo.html")


class PrivacyPolicyView(View):
    def get(self, request):
        return render(
            request,
            "tracker/privacy.html",
            {
                "data_usage": [
                    {
                        "item": "Email address",
                        "purpose": "Used to identify your account, keep your session tied to your data, and let you know which Google account is connected.",
                    },
                    {
                        "item": "Basic profile (name)",
                        "purpose": "Displayed in the app header so you can quickly see which account is active.",
                    },
                    {
                        "item": "Google Sheets access",
                        "purpose": "Lets Amiibo Tracker create and update your AmiiboCollection sheet so we can store your collection status and dark mode preference without touching any other documents.",
                    },
                ]
            },
        )


class AmiiboDatabaseView(
    View, LoggingMixin, AmiiboRemoteFetchMixin, AmiiboLocalFetchMixin
):
    def get(self, request):
        remote_amiibos = self._fetch_remote_amiibos()

        if remote_amiibos:
            amiibos = remote_amiibos
            local_amiibos = self._fetch_local_amiibos()
            self._log_missing_remote_items(local_amiibos, remote_amiibos)
        else:
            amiibos = self._fetch_local_amiibos()

        if not amiibos:
            return JsonResponse(
                {"status": "error", "message": "Amiibo database unavailable."},
                status=500,
            )

        filtered_amiibos = self._filter_amiibos(amiibos, request)

        if request.GET.get("showusage") is not None and remote_amiibos:
            filtered_amiibos = self._attach_usage_data(filtered_amiibos, remote_amiibos)

        return JsonResponse({"amiibo": filtered_amiibos}, safe=False)

    @staticmethod
    def _filter_amiibos(amiibos: list[dict], request):
        name_filter = request.GET.get("name")
        game_series_filter = request.GET.get("gameseries") or request.GET.get(
            "gameSeries"
        )
        character_filter = request.GET.get("character")

        def matches(value, query):
            return query.lower() in (value or "").lower()

        filtered = []
        for amiibo in amiibos:
            if name_filter and not matches(amiibo.get("name"), name_filter):
                continue
            if game_series_filter and not matches(
                amiibo.get("gameSeries"), game_series_filter
            ):
                continue
            if character_filter and not matches(
                amiibo.get("character"), character_filter
            ):
                continue
            filtered.append(dict(amiibo))

        return filtered

    def _log_missing_remote_items(self, local_amiibos: list[dict], remote_amiibos):
        local_ids = {
            f"{amiibo.get('head', '')}{amiibo.get('tail', '')}"
            for amiibo in local_amiibos
            if amiibo.get("head") and amiibo.get("tail")
        }

        missing_remote = [
            amiibo
            for amiibo in remote_amiibos
            if amiibo.get("head")
            and amiibo.get("tail")
            and f"{amiibo.get('head')}{amiibo.get('tail')}" not in local_ids
        ]

        if missing_remote:
            self.log_warning(
                "amiibo-database-missing-items",
                missing_count=len(missing_remote),
                missing_ids=[
                    f"{amiibo.get('name', 'unknown')} ({amiibo.get('head')}{amiibo.get('tail')})"
                    for amiibo in missing_remote
                ],
            )

    @staticmethod
    def _attach_usage_data(amiibos: list[dict], remote_amiibos: list[dict]):
        usage_keys = ["gamesSwitch", "games3DS", "gamesWiiU"]
        remote_lookup = {
            f"{amiibo.get('head')}{amiibo.get('tail')}": amiibo
            for amiibo in remote_amiibos
            if amiibo.get("head") and amiibo.get("tail")
        }

        enriched = []
        for amiibo in amiibos:
            amiibo_id = f"{amiibo.get('head', '')}{amiibo.get('tail', '')}"
            remote_match = remote_lookup.get(amiibo_id, {})
            amiibo_with_usage = dict(amiibo)
            for key in usage_keys:
                if key in remote_match:
                    amiibo_with_usage[key] = remote_match[key]
            enriched.append(amiibo_with_usage)

        return enriched


class BlogListView(View, LoggingMixin):
    def get(self, request):
        self.log_action(
            "blog-list-view",
            request,
            total_posts=len(BLOG_POSTS),
        )
        return render(request, "tracker/blog_list.html", {"posts": BLOG_POSTS})


class BlogPostView(View, LoggingMixin, AmiiboRemoteFetchMixin):
    def get(self, request, slug):
        post = next((p for p in BLOG_POSTS if p["slug"] == slug), None)
        if not post:
            from django.http import Http404

            self.log_action(
                "blog-post-not-found",
                request,
                level="warning",
                slug=slug,
            )
            raise Http404("Blog post not found")

        self.log_action(
            "blog-post-view",
            request,
            slug=slug,
            title=post["title"],
        )

        context = {"post": post}

        # Handle dynamic content for number-released post
        if slug == "number-released" and post.get("content") == "dynamic":
            try:
                amiibos = self._fetch_remote_amiibos()

                # Add formatted release date for each amiibo
                for amiibo in amiibos:
                    amiibo["display_release"] = AmiiboService._format_release_date(
                        amiibo.get("release")
                    )
                    # Extract the earliest release date for sorting
                    release_dates = amiibo.get("release", {})
                    earliest_date = None
                    for region in ["na", "jp", "eu", "au"]:
                        date_str = release_dates.get(region)
                        if date_str:
                            try:
                                from datetime import datetime

                                date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                                if earliest_date is None or date_obj < earliest_date:
                                    earliest_date = date_obj
                            except (ValueError, TypeError):
                                pass
                    amiibo["earliest_release"] = earliest_date

                # Sort by earliest release date (newest first), then by name
                sorted_amiibos = sorted(
                    amiibos,
                    key=lambda x: (
                        x["earliest_release"] is None,  # Put None dates at end
                        x["earliest_release"] if x["earliest_release"] else "",
                        x.get("name", ""),
                    ),
                    reverse=True,  # Newest first
                )

                context["amiibos"] = sorted_amiibos
                context["total_count"] = len(sorted_amiibos)

                self.log_action(
                    "blog-dynamic-content-loaded",
                    request,
                    slug=slug,
                    amiibo_count=len(sorted_amiibos),
                )
            except Exception as e:
                self.log_action(
                    "blog-dynamic-content-error",
                    request,
                    level="error",
                    slug=slug,
                    error=str(e),
                )
                context["amiibos"] = []
                context["total_count"] = 0
                context["error"] = True

        return render(request, "tracker/blog_post.html", context)
