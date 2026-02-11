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
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.http import JsonResponse, Http404, HttpResponse
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
from tracker.seo_helpers import (
    SEOContext,
    generate_meta_description,
    generate_article_schema,
    generate_product_schema,
    generate_breadcrumb_schema,
    generate_organization_schema,
    generate_website_schema,
)
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


def load_blog_posts():
    """Load blog posts from JSON file."""
    blog_posts_path = Path(__file__).parent / "data" / "blog_posts.json"
    try:
        with blog_posts_path.open(encoding="utf-8") as f:
            data = json.load(f)
            return data.get("posts", [])
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"Error loading blog posts: {e}")
        return []


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
    {
        "slug": "animal-crossing-amiibo-guide-2026",
        "title": "Complete Animal Crossing New Horizons Amiibo Compatibility Guide (2026)",
        "date": "2026-02-10",
        "excerpt": "Discover how Animal Crossing amiibo unlock villagers, furniture, and exclusive items in New Horizons with this comprehensive compatibility guide.",
        "content": """
<h2>Introduction to Animal Crossing Amiibo</h2>
<p>Since Animal Crossing: New Horizons launched in March 2020, amiibo functionality has become an essential tool for collectors and players seeking specific villagers or exclusive furniture sets. Unlike many games where amiibo provide minor bonuses, Animal Crossing offers substantial rewards: the ability to invite specific villagers to your island, unlock exclusive furniture collections, and collect character posters for decorating your home.</p>

<p>The Animal Crossing amiibo ecosystem includes over 500 compatible figures and cards spanning multiple series, from the original Animal Crossing amiibo card series (Series 1-5) to Sanrio Collaboration cards and Super Smash Bros. Isabelle and Villager figures. Understanding what each amiibo unlocks can save you time, bells, and frustration when building your dream island.</p>

<div style="text-align: center; margin: 2rem 0;">
    <img src="{% static 'images/blog/animal-crossing-amiibo-cards.jpg' %}"
         alt="Animal Crossing amiibo cards spread out showing various villagers"
         style="max-width: 100%; height: auto; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.3);">
    <p style="font-size: 0.9rem; color: rgba(253, 247, 227, 0.7); margin-top: 0.5rem; font-style: italic;">Animal Crossing amiibo cards feature hundreds of unique villagers</p>
</div>

<h2>How Amiibo Work in New Horizons</h2>
<p>To use amiibo in Animal Crossing: New Horizons, you must first unlock the campsite facility by progressing through Tom Nook's story missions. Once the campsite is built (typically after your 5th-6th resident moves in), you can scan amiibo at the Resident Services terminal using the "Invite a Camper" option.</p>

<h3>The Invitation Process</h3>
<p>When you scan a villager amiibo card or figure, the character visits your campsite the same day. However, you cannot immediately invite them to move in. The process requires:</p>
<ul>
    <li><strong>Day 1:</strong> Scan the amiibo, meet the villager at the campsite, complete a DIY crafting request</li>
    <li><strong>Day 2:</strong> Scan the same amiibo again, complete another DIY request</li>
    <li><strong>Day 3:</strong> Scan for the third time, complete the final request, then invite them to stay permanently</li>
</ul>

<p>This three-day process applies to all villager amiibo. The villager will request specific DIY furniture items, which you must craft using materials from your island. Once invited on Day 3, you can choose which current resident they replace (if your island is at the 10-villager maximum) or they'll move into an empty plot.</p>

<h2>Villager Compatibility by Series</h2>

<h3>Animal Crossing Amiibo Cards (Series 1-5)</h3>
<p>Nintendo released five main Animal Crossing amiibo card series between 2015-2016, containing 100 cards each for a total of 500 unique villagers and special characters. All non-special character cards (like regular villagers) work with the campsite invitation system described above.</p>

<p style="font-size: 1.15rem; color: var(--saffron); margin: 1.5rem 0;">Key fact: All 391 regular villagers from Series 1-5 can be invited to your island using their amiibo cards.</p>

<p><strong>Special Character Cards (Series 1-5):</strong> Cards featuring special characters like Tom Nook (#002), K.K. Slider (#003), Isabelle (#001), or Celeste (#305) cannot be invited as residents. Instead, they unlock exclusive posters at Harv's Island photoshoot studio, which you can then order from the Nook Shopping catalog for 1,000 bells each.</p>

<h3>Welcome Amiibo Series (Series 6)</h3>
<p>Released in November 2016 alongside Animal Crossing: New Leaf - Welcome amiibo, this 50-card series features villagers that were previously exclusive to the 3DS title. In New Horizons, these cards work identically to Series 1-5, allowing you to invite villagers like Vivian (#01), Ursala (#09), or Gonzo (#42) to your island following the three-day invitation process.</p>

<h3>Sanrio Collaboration Cards</h3>
<p>Perhaps the most sought-after amiibo cards, the Sanrio Collaboration pack contains 6 cards featuring Hello Kitty-themed villagers: Rilla, Marty, Étoile, Chai, Chelsea, and Toby. These cards unlock two exclusive features:</p>
<ul>
    <li><strong>Villager Invitations:</strong> You can invite any of the 6 Sanrio villagers to your island using the standard three-day process</li>
    <li><strong>Exclusive Furniture Sets:</strong> Once a Sanrio villager visits your campsite, their entire themed furniture set becomes available in Nook Shopping's Promotion tab, including items like the Hello Kitty bed, Cinnamoroll table, Pompompurin TV, and My Melody dress</li>
</ul>

<p>Originally released in 2016 and re-released in March 2021, these cards regularly sell out within minutes due to high demand. The furniture sets cannot be obtained any other way in New Horizons.</p>

<h3>Super Smash Bros. Series</h3>
<p>Two Super Smash Bros. amiibo unlock special functionality:</p>
<ul>
    <li><strong>Villager (#009):</strong> Unlocks the Villager poster only; cannot be invited as a resident since "Villager" is the player character</li>
    <li><strong>Isabelle (#011):</strong> Unlocks the Isabelle poster only; she's a special NPC and cannot be invited to live on your island</li>
</ul>

<h2>Furniture and Item Unlocks by Franchise</h2>
<p>Beyond villager invitations, many amiibo from other Nintendo franchises unlock exclusive posters and, in some cases, themed furniture items. Here's what each franchise provides:</p>

<h3>The Legend of Zelda Series</h3>
<p>Scanning any Zelda-themed amiibo (Link, Zelda, Ganondorf, Guardian, Bokoblin, etc.) unlocks character posters featuring the respective character. No exclusive furniture sets are available, but the posters feature beautiful artwork from various Zelda games.</p>

<h3>Super Mario Series</h3>
<p>Mario, Luigi, Peach, Bowser, and other Mario franchise amiibo unlock character posters. The Super Mario series particularly offers vibrant, colorful poster designs perfect for arcade or game room-themed island areas.</p>

<h3>Splatoon Series</h3>
<p>Inkling Boy, Inkling Girl, and other Splatoon amiibo unlock Splatoon character posters. These feature dynamic, street art-inspired designs that complement urban or graffiti-themed island builds.</p>

<h3>Other Compatible Amiibo</h3>
<p>Nearly every Nintendo amiibo figure and card unlocks at least a poster in New Horizons. Compatible franchises include: Metroid, Kirby, Star Fox, Fire Emblem, Pikmin, and many more. With over 200+ amiibo figures released since 2014, the poster collection potential is enormous.</p>

<h2>Poster Collection Guide</h2>
<p>Once you unlock Harv's Island (accessible after recruiting three villagers), you can scan any compatible amiibo at the photoshoot studio. After scanning, the character's poster becomes available in your Nook Shopping catalog under the "Posters" category.</p>

<h3>How to Order Posters</h3>
<p>Visit Harv's Island, enter the studio, and press down on the D-pad to open the decorating menu. Select "Amiibo" and scan any compatible amiibo card or figure. The character appears as a decoration in the studio, and their poster is immediately added to your catalog. Return to Resident Services or use the Nook Shopping app on your NookPhone to order posters for 1,000 bells each (delivered the next day).</p>

<h2>Advanced Tips and Strategies</h2>

<h3>Villager Hunting Optimization</h3>
<p>If you're seeking a specific villager without their amiibo card, you'll need to use Nook Miles Tickets to visit mystery islands, hoping for random encounters. However, amiibo cards guarantee the villager you want, saving potentially hundreds of Nook Miles Tickets and hours of searching. Popular villagers like Raymond, Sherb, or Judy can take 200+ mystery island visits to find naturally but require only three days with an amiibo card.</p>

<h3>Replacing Unwanted Villagers</h3>
<p>The amiibo method is the only way to choose which villager leaves your island when inviting a new resident. When you invite an amiibo villager on Day 3 and your island has 10 residents, Tom Nook asks which current villager should move out to make room. This bypasses the random move-out process, giving you complete control.</p>

<h3>Time Travel Considerations</h3>
<p>Players who use time travel can complete the three-day amiibo invitation process in minutes by advancing the date after each scan. This accelerates villager collection but may impact turnip prices and other time-sensitive events.</p>

<h3>Fake vs. Authentic Cards</h3>
<p>Due to high demand, counterfeit amiibo cards flood online marketplaces. Authentic cards feature official Nintendo packaging, high-quality card stock, and clear printing. Unofficial cards (while functionally identical) violate Nintendo's intellectual property. If purchasing secondhand, verify authenticity through seller ratings and detailed photos.</p>

<p style="font-size: 1.15rem; color: var(--saffron); margin: 1.5rem 0;">Pro tip: Official amiibo cards have a matte finish, while many counterfeits use glossy card stock.</p>

<h2>Conclusion</h2>
<p>Animal Crossing: New Horizons offers deep amiibo integration that enhances the core gameplay experience without being required. Whether you're hunting for dreamies, collecting all 391 villager cards, or decorating with exclusive Sanrio furniture, amiibo provide meaningful shortcuts and unlocks. With proper understanding of compatibility, invitation mechanics, and poster collection, you can maximize your amiibo investment and build the perfect island community.</p>
""",
    },
    {
        "slug": "zelda-tears-kingdom-amiibo-unlocks",
        "title": "Amiibo in The Legend of Zelda: Tears of the Kingdom - Complete Unlock Database",
        "date": "2026-02-10",
        "excerpt": "Unlock exclusive gear, paraglider fabrics, and rare materials in Tears of the Kingdom using Zelda amiibo. Complete compatibility guide for all figures.",
        "content": """
<h2>How Amiibo Work in Tears of the Kingdom</h2>
<p>The Legend of Zelda: Tears of the Kingdom (released May 12, 2023) features extensive amiibo support, building upon the foundation established in Breath of the Wild. Unlike many games where amiibo provide minor cosmetic bonuses, TOTK amiibo drop valuable weapons, materials, and exclusive paraglider fabrics that cannot be obtained through normal gameplay.</p>

<p>Each amiibo can be scanned once per day (real-world time, not in-game time). Scanning creates a glowing pillar of light that drops items from the sky, containing a random selection of materials and, occasionally, exclusive equipment. The drops scale with your game progress, providing stronger weapons and rarer materials as you advance through Hyrule.</p>

<div style="text-align: center; margin: 2rem 0;">
    <img src="{% static 'images/blog/zelda-totk-amiibo.jpg' %}"
         alt="Link amiibo being scanned on Nintendo Switch for Tears of the Kingdom"
         style="max-width: 100%; height: auto; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.3);">
    <p style="font-size: 0.9rem; color: rgba(253, 247, 227, 0.7); margin-top: 0.5rem; font-style: italic;">Scan Link amiibo to unlock exclusive gear and paraglider fabrics</p>
</div>

<h3>How to Scan Amiibo</h3>
<p>After completing the tutorial on the Great Sky Island (approximately 2-3 hours of gameplay), the amiibo feature unlocks automatically. Press up on the D-pad to open the quick menu, navigate to the amiibo icon (rightmost option), and hold your amiibo figure or card to the NFC touchpoint on your right Joy-Con or Pro Controller. A brief loading screen confirms the scan, and items drop near Link's location.</p>

<h2>Link Amiibo Unlocks (All Variants)</h2>

<h3>Tears of the Kingdom Link & Zelda Amiibo</h3>
<p>Nintendo released two new amiibo figures alongside TOTK's launch: Link (Tears of the Kingdom) and Zelda (Tears of the Kingdom). These figures unlock unique paraglider fabrics not available through any other method:</p>
<ul>
    <li><strong>Link (TOTK):</strong> Unlocks the "Hyrule Zelda Fabric" paraglider design featuring TOTK's key art</li>
    <li><strong>Zelda (TOTK):</strong> Unlocks the "Princess Zelda Fabric" paraglider design with a royal aesthetic</li>
</ul>
<p>Additionally, these amiibo drop meat, fish, plants, and occasionally weapons from the "Of the Kingdom" set, which feature TOTK-specific designs.</p>

<h3>Breath of the Wild Link Variants</h3>
<p>Multiple Link amiibo from the Breath of the Wild era offer different reward pools:</p>

<p><strong>Link (Archer) - BOTW:</strong></p>
<ul>
    <li>Drops: Arrows (x5-20), bows, plants, and occasionally the "Tunic of Memories" armor set</li>
    <li>Exclusive Fabric: None</li>
    <li>Strategy: Best scanned when you need arrow restocks during mid-game exploration</li>
</ul>

<p><strong>Link (Rider) - BOTW:</strong></p>
<ul>
    <li>Drops: Saddles, horse equipment, plants, raw meat</li>
    <li>Exclusive Fabric: "Hyrule-Ridge Fabric"</li>
    <li>Special Feature: Can summon Epona, Link's iconic horse from Ocarina of Time, which has max stats (4-4-4)</li>
</ul>

<p style="font-size: 1.15rem; color: var(--saffron); margin: 1.5rem 0;">Epona is the only horse in TOTK with perfectly balanced stats and unique coloring.</p>

<p><strong>Link (Climber) - BOTW:</strong></p>
<ul>
    <li>Drops: Climbing gear, stamina-restoring food, ore, plants</li>
    <li>Exclusive Fabric: None</li>
    <li>Best Use: Early game when stamina management is critical for exploration</li>
</ul>

<h3>Super Smash Bros. Series Link Variants</h3>
<p>The Super Smash Bros. line includes multiple Link iterations, each with unique drops:</p>

<p><strong>Link (Super Smash Bros.):</strong></p>
<ul>
    <li>Drops: General weapons, materials, occasional rare gems</li>
    <li>Exclusive Items: Can drop the "Sword of the Sky" when RNG favors you</li>
    <li>Paraglider Fabric: "Hero of Hyrule Fabric" (classic green tunic design)</li>
</ul>

<p><strong>Young Link (Super Smash Bros.):</strong></p>
<ul>
    <li>Drops: Forest-themed items, wood, acorns, Kokiri-style equipment</li>
    <li>Exclusive Fabric: None</li>
</ul>

<p><strong>Toon Link (Super Smash Bros.):</strong></p>
<ul>
    <li>Drops: Naval-themed items, fish, occasional sea breeze boomerang</li>
    <li>Exclusive Fabric: "King of Red Lions Fabric" (Wind Waker boat design)</li>
</ul>

<h3>Specialty Link Amiibo</h3>
<p><strong>8-Bit Link (The Legend of Zelda):</strong></p>
<ul>
    <li>Drops: Rupees, basic weapons, occasional barrels with random loot</li>
    <li>Exclusive Items: Can drop 8-bit sword and shield (cosmetic retro weapons)</li>
    <li>Paraglider Fabric: "Pixel Fabric" (8-bit Zelda sprite design)</li>
</ul>

<p><strong>Link's Awakening Link:</strong></p>
<ul>
    <li>Drops: Shells, fish, island-themed materials</li>
    <li>Exclusive Fabric: "Koholint Fabric" (Link's Awakening art style)</li>
</ul>

<h2>Other Zelda Series Amiibo</h2>

<h3>Zelda (Multiple Variants)</h3>
<p>Zelda amiibo typically drop plants, herbs, star fragments, and occasionally shields or bows:</p>
<ul>
    <li><strong>Zelda (Super Smash Bros.):</strong> Drops shields, light-themed weapons, occasional Hylian Shield replica</li>
    <li><strong>Zelda (BOTW):</strong> Drops plants, star fragments, royal equipment</li>
    <li><strong>Zelda (TOTK):</strong> Drops Princess-themed items, mentioned above with exclusive fabric</li>
</ul>

<h3>Ganondorf</h3>
<p>The Ganondorf amiibo (Super Smash Bros.) drops dark-themed weapons, meat, monster parts, and occasionally powerful two-handed swords. While no exclusive fabric is unlocked, the drops tend toward high-damage weapons useful in combat.</p>

<h3>Guardian</h3>
<p>The Guardian amiibo (BOTW) drops ancient materials, gears, springs, screws, and cores. This is one of the most valuable amiibo for players farming ancient materials to upgrade armor sets at the Akkala Ancient Tech Lab, as ancient materials are time-consuming to gather naturally.</p>

<h3>Bokoblin</h3>
<p>The Bokoblin amiibo (BOTW) drops monster parts, weapons, meat, and occasionally rare monster extracts. Useful for players completing Kilton's monster-part requests or upgrading specific armor sets requiring enemy drops.</p>

<h2>Cross-Series Compatibility</h2>
<p>Many non-Zelda amiibo provide generic drops in Tears of the Kingdom, though without exclusive equipment or fabrics:</p>

<h3>Compatible Nintendo Franchises</h3>
<ul>
    <li><strong>Super Mario Series:</strong> Drops mushrooms, plants, occasional weapons</li>
    <li><strong>Splatoon Series:</strong> Drops fish, seafood, occasional treasure chests with random loot</li>
    <li><strong>Animal Crossing Series:</strong> Drops plants, fruit, wood, building materials</li>
    <li><strong>Metroid Series:</strong> Drops meat, ore, monster parts</li>
    <li><strong>Fire Emblem Series:</strong> Drops weapons, shields, occasional knight-themed equipment</li>
    <li><strong>Kirby Series:</strong> Drops food items, star fragments, occasional recovery items</li>
</ul>

<p>While these amiibo don't unlock exclusive TOTK content, they can still provide useful materials and weapons, making them worthwhile to scan daily if you own them.</p>

<h2>Paraglider Fabric Collection</h2>
<p>One of the most collectible aspects of TOTK amiibo integration is the exclusive paraglider fabric designs. These cosmetic patterns customize your paraglider's appearance and cannot be obtained without scanning specific amiibo.</p>

<h3>Complete Fabric List (Amiibo-Exclusive)</h3>
<ul>
    <li>Hyrule Zelda Fabric (Link TOTK amiibo)</li>
    <li>Princess Zelda Fabric (Zelda TOTK amiibo)</li>
    <li>Hyrule-Ridge Fabric (Link Rider BOTW amiibo)</li>
    <li>Hero of Hyrule Fabric (Link Super Smash Bros. amiibo)</li>
    <li>King of Red Lions Fabric (Toon Link Super Smash Bros. amiibo)</li>
    <li>Pixel Fabric (8-Bit Link amiibo)</li>
    <li>Koholint Fabric (Link's Awakening Link amiibo)</li>
</ul>

<p>Completionists note: These 7 fabrics represent the core amiibo-exclusive designs, though additional Link variants may offer alternative patterns.</p>

<h2>Farming Strategies and Best Practices</h2>

<h3>Daily Scan Optimization</h3>
<p>Since each amiibo can only be scanned once per real-world day (resets at midnight local time), strategic players prioritize their most valuable amiibo:</p>
<ul>
    <li><strong>Early Game (Great Sky Island to Lookout Landing):</strong> Scan Link (Climber) for stamina food and climbing gear</li>
    <li><strong>Mid Game (Exploring surface Hyrule):</strong> Scan Guardian for ancient materials and Link (Rider) for Epona</li>
    <li><strong>Late Game (Final dungeons and boss preparation):</strong> Scan Ganondorf or Link (Archer) for powerful weapons and arrows</li>
</ul>

<h3>Save Scumming Technique</h3>
<p>Some players use "save scumming" to maximize amiibo drops. The process involves:</p>
<ol>
    <li>Create a manual save before scanning an amiibo</li>
    <li>Scan the amiibo and check the drops</li>
    <li>If drops are unsatisfactory, reload the save and rescan</li>
    <li>Repeat until desired items appear</li>
</ol>
<p>This technique works because amiibo drop pools use RNG determined at the moment of scanning, not when the day resets. However, it's time-consuming and somewhat undermines the intended gameplay experience.</p>

<h3>Time Travel Considerations</h3>
<p>Unlike Animal Crossing, TOTK does not penalize changing your Switch's system clock. Players who adjust their console's date can scan the same amiibo multiple times by advancing the date forward, then returning to the current date. This allows rapid farming of materials or multiple attempts at rare drops without waiting days.</p>

<h2>Comparison to Breath of the Wild</h2>
<p>TOTK's amiibo functionality largely mirrors BOTW with key improvements:</p>
<ul>
    <li><strong>More Exclusive Fabrics:</strong> TOTK added 2 new fabrics with the launch amiibo, expanding customization options</li>
    <li><strong>Scaled Drops:</strong> Weapons and materials scale more intelligently with player progression</li>
    <li><strong>Consistent Compatibility:</strong> All BOTW-compatible amiibo work in TOTK, ensuring your collection remains valuable</li>
</ul>

<h2>Conclusion</h2>
<p>Tears of the Kingdom offers robust amiibo support that rewards collectors with exclusive paraglider designs, rare materials, and powerful equipment. While amiibo are entirely optional (no content is locked behind them except cosmetic fabrics), they provide convenient daily bonuses that enhance the exploration experience. Whether you're farming ancient materials with the Guardian amiibo, summoning Epona with Link (Rider), or collecting all 7 exclusive paraglider fabrics, TOTK ensures your amiibo collection has meaningful utility in one of Nintendo's most ambitious adventures.</p>
""",
    },
    {
        "slug": "switch-2-amiibo-compatibility",
        "title": "Switch 2 Launch Titles: Which Amiibo Will Work? Compatibility Predictions",
        "date": "2026-02-10",
        "excerpt": "With Nintendo Switch 2 on the horizon, explore what we know about amiibo compatibility, NFC technology, and which figures will work with launch titles.",
        "content": """
<h2>Historical Precedent: Wii U to Switch Transition</h2>
<p>To understand how amiibo will function on Switch 2, we must examine Nintendo's track record when transitioning console generations. When the Nintendo Switch launched on March 3, 2017, Nintendo maintained full backward compatibility with all amiibo released since the platform's 2014 debut. Every single amiibo figure and card designed for Wii U and 3DS worked seamlessly with Switch games like The Legend of Zelda: Breath of the Wild, Super Mario Odyssey, and Splatoon 2.</p>

<p>This universal compatibility made business sense: Nintendo had sold millions of amiibo by 2017, and collectors had invested hundreds or thousands of dollars in their collections. Breaking compatibility would have alienated this dedicated fanbase while providing no technical benefit. The Switch's NFC reader (built into the right Joy-Con) used the same NFC Type 2 Tag technology as its predecessors, ensuring effortless continuity.</p>

<div style="text-align: center; margin: 2rem 0;">
    <img src="{% static 'images/blog/amiibo-collection-lineup.jpg' %}"
         alt="Collection of various amiibo figures lined up"
         style="max-width: 100%; height: auto; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.3);">
    <p style="font-size: 0.9rem; color: rgba(253, 247, 227, 0.7); margin-top: 0.5rem; font-style: italic;">Your existing amiibo collection will work with Switch 2</p>
</div>

<p style="font-size: 1.15rem; color: var(--saffron); margin: 1.5rem 0;">Key insight: Nintendo has never discontinued amiibo compatibility across console generations, suggesting Switch 2 will follow this pattern.</p>

<h2>NFC Technology in Switch 2</h2>
<p>While Nintendo has not officially announced Switch 2 specifications as of February 2026, industry analysis and patent filings suggest the console will retain NFC functionality with potential enhancements:</p>

<h3>Expected NFC Features</h3>
<ul>
    <li><strong>NFC Type 2 Tag Support:</strong> The same standard used in all current amiibo, ensuring backward compatibility</li>
    <li><strong>Improved Read Range:</strong> Patents filed by Nintendo in 2024 reference "enhanced proximity detection," potentially allowing scanning from slightly greater distances</li>
    <li><strong>Faster Communication:</strong> More powerful hardware could reduce scan times from ~2 seconds to under 1 second</li>
    <li><strong>Multi-Tag Reading:</strong> Speculative feature that might allow scanning multiple amiibo simultaneously (unconfirmed)</li>
</ul>

<h3>Controller Integration</h3>
<p>Based on leaked accessory designs and FCC filings, Switch 2's controllers (tentatively called "Joy-Con 2") will include NFC readers in the right controller, maintaining the same placement as current Joy-Cons. This ensures existing muscle memory translates directly, and docked gameplay remains compatible with amiibo.</p>

<h2>Confirmed Compatible Amiibo</h2>
<p>While official confirmation awaits Nintendo's formal announcement, we can reasonably predict amiibo compatibility based on precedent and technical feasibility:</p>

<h3>100% Expected Compatibility</h3>
<ul>
    <li><strong>All Super Smash Bros. Series:</strong> 89+ figures spanning every Smash Ultimate character</li>
    <li><strong>The Legend of Zelda Series:</strong> 25+ figures including Link variants, Zelda, Guardians, and Champions</li>
    <li><strong>Super Mario Series:</strong> 40+ figures covering Mario, Luigi, Peach, Bowser, and extended cast</li>
    <li><strong>Splatoon Series:</strong> 20+ figures including Inklings, Octolings, and Splatoon 3 idols</li>
    <li><strong>Animal Crossing Series:</strong> 500+ cards plus figures of Isabelle, Tom Nook, and villagers</li>
    <li><strong>Pokémon Series:</strong> 15+ figures including Pikachu, Lucario, Mewtwo, and Detective Pikachu</li>
    <li><strong>Metroid Series:</strong> Samus variants and Metroid figures from Samus Returns and Dread</li>
    <li><strong>Fire Emblem Series:</strong> Marth, Roy, Ike, and other lords from the tactical RPG franchise</li>
    <li><strong>All Other Nintendo Franchises:</strong> Kirby, Star Fox, F-Zero, Xenoblade, and more</li>
</ul>

<p>This encompasses approximately 800+ unique amiibo products released between 2014-2026, representing Nintendo's entire amiibo library. Given the technological simplicity of maintaining NFC compatibility and the business incentive to support existing collections, discontinuing support for any amiibo line would be unprecedented and illogical.</p>

<h2>Enhanced Features for Switch 2</h2>
<p>Beyond basic compatibility, Switch 2 games may introduce enhanced amiibo functionality leveraging the console's improved hardware:</p>

<h3>Potential Enhancements</h3>
<ul>
    <li><strong>High-Resolution Textures:</strong> Amiibo-unlocked costumes or items could feature 4K textures matching Switch 2's rumored graphics capabilities</li>
    <li><strong>Expanded Data Storage:</strong> While current amiibo use minimal writable storage (most data is read-only), Switch 2 games might utilize more sophisticated save data on figures</li>
    <li><strong>Dynamic Lighting Effects:</strong> Games could implement real-time lighting changes when amiibo are scanned, such as in-game statues materializing with particle effects</li>
    <li><strong>Cross-Game Progression:</strong> A hypothetical "Nintendo Ecosystem" could allow amiibo to carry progression or rewards across multiple Switch 2 titles</li>
</ul>

<h3>Speculative: Amiibo 2.0?</h3>
<p>Some analysts speculate Nintendo might introduce "Amiibo 2.0" figures with enhanced NFC chips offering more storage or additional sensors. However, this seems unlikely given:</p>
<ul>
    <li>Nintendo's commitment to simplicity and backward compatibility</li>
    <li>The added manufacturing cost would increase retail prices</li>
    <li>Fragmenting the amiibo ecosystem into "old" and "new" versions alienates collectors</li>
</ul>

<p>More probable: Nintendo continues the current amiibo format while introducing new character figures and card series tied to Switch 2 launch titles.</p>

<h2>Predicted New Amiibo Lines</h2>
<p>Based on Nintendo's release patterns and rumored Switch 2 launch titles, several new amiibo lines seem likely:</p>

<h3>Mario Kart 9 Series</h3>
<p>If Mario Kart 9 launches alongside Switch 2 (as Mario Kart 8 did with Wii U in 2014), expect a new wave of Mario Kart-themed amiibo featuring:</p>
<ul>
    <li>Mario, Luigi, Peach, and Bowser in racing suits</li>
    <li>New character additions (potentially Pauline, Nabbit, or Toadette variants)</li>
    <li>Vehicle-themed stands or dynamic poses</li>
</ul>
<p>Functionality would likely unlock custom kart parts, character skins, or bonus race tracks exclusive to amiibo owners.</p>

<h3>3D Mario (Mario Odyssey 2 or New IP)</h3>
<p>Nintendo's flagship 3D Mario titles traditionally receive robust amiibo support. A sequel to Super Mario Odyssey or a brand-new 3D Mario adventure could introduce:</p>
<ul>
    <li>Mario in new capture transformations (T-Rex Mario, Lava Mario, etc.)</li>
    <li>Cappy as a standalone amiibo</li>
    <li>New capture-based NPCs or bosses</li>
</ul>

<h3>Splatoon 4 or Splatoon DLC</h3>
<p>The Splatoon franchise has consistently released new amiibo with each installment. Splatoon 4 (or major Splatoon 3 DLC for Switch 2) would almost certainly feature:</p>
<ul>
    <li>New Inkling and Octoling variants with updated hairstyles</li>
    <li>New idol group characters (following Deep Cut from Splatoon 3)</li>
    <li>Exclusive gear sets unlockable via amiibo scanning</li>
</ul>

<h3>Metroid Prime 4</h3>
<p>After years of development, Metroid Prime 4 is expected to launch near Switch 2's release window. Potential amiibo include:</p>
<ul>
    <li>Samus in her Prime 4 suit design</li>
    <li>New antagonists or bosses from the game</li>
    <li>Classic Metroid creature amiibo (Ridley variant, Space Pirate, etc.)</li>
</ul>
<p>Functionality might unlock concept art galleries, difficulty modifiers, or exclusive weapon skins.</p>

<h2>The Collector's Perspective</h2>
<p>For dedicated amiibo collectors, Switch 2's backward compatibility offers peace of mind. Your existing collection—whether 10 figures or 500 cards—will retain full functionality in Switch 2 games. This preserves the investment of both money and display space dedicated to amiibo over the past decade.</p>

<h3>Should You Buy Amiibo Now?</h3>
<p>Given near-certain backward compatibility, purchasing amiibo before Switch 2's launch carries minimal risk. In fact, buying now may be advantageous:</p>
<ul>
    <li><strong>Avoid Launch Shortages:</strong> New console launches often create supply chain strain, potentially causing amiibo restocks delays</li>
    <li><strong>Lock in Current Prices:</strong> Popular amiibo may see price increases as Switch 2 hype builds</li>
    <li><strong>Complete Your Switch 1 Collection:</strong> Any amiibo you want from the Switch era will work on Switch 2, so there's no reason to wait</li>
</ul>

<h2>What We're Still Waiting to Learn</h2>
<p>Until Nintendo's official Switch 2 reveal (expected in early-to-mid 2026), several questions remain:</p>
<ul>
    <li><strong>Day-One Amiibo Support:</strong> Will launch titles include amiibo functionality, or will it be added post-launch via updates?</li>
    <li><strong>Legacy Game Compatibility:</strong> If Switch 2 supports backward compatibility with Switch 1 games, will amiibo function in those older titles?</li>
    <li><strong>New Manufacturing Partnerships:</strong> Will Nintendo introduce new figure manufacturers or card printers, potentially affecting quality or availability?</li>
    <li><strong>Digital Amiibo:</strong> Could Nintendo introduce a "digital amiibo" system allowing players to purchase NFC data without physical figures? (Speculative and unlikely given Nintendo's toy-focused strategy)</li>
</ul>

<h2>Conclusion</h2>
<p>Based on historical precedent, technical feasibility, and business logic, amiibo collectors can confidently expect full backward compatibility on Switch 2. Nintendo's decade-long commitment to the amiibo platform, combined with the negligible cost of maintaining NFC support, makes discontinuing compatibility virtually impossible. As Switch 2 approaches, collectors should feel secure in their investments, knowing their carefully curated libraries will enhance the next generation of Nintendo gaming just as they have since 2014.</p>

<p style="font-size: 1.15rem; color: var(--saffron); margin: 1.5rem 0;">The future of amiibo looks bright—your collection is safe, functional, and ready for Switch 2's launch.</p>
""",
    },
    {
        "slug": "amiibo-rarity-guide-2026",
        "title": "Amiibo Rarity Tier List 2026: From Common to Unicorn Status",
        "date": "2026-02-10",
        "excerpt": "Navigate the amiibo secondary market with this comprehensive rarity guide covering unicorns, regional exclusives, and common finds in 2026.",
        "content": """
<h2>Understanding Amiibo Rarity</h2>
<p>Since the infamous "Holy Trinity" shortage of 2014-2015 (Marth, Villager, and Wii Fit Trainer), amiibo rarity has fascinated collectors and frustrated completionists. Unlike most toy lines where supply eventually meets demand, amiibo scarcity stems from Nintendo's conservative production runs, regional exclusivity deals, and unpredictable character popularity. A figure common at launch may become rare years later, while supposed "unicorns" occasionally see surprise restocks.</p>

<p>This guide categorizes amiibo rarity as of February 2026, reflecting current secondary market prices, retail availability, and community consensus. Note that rarity fluctuates with restocks, new releases, and shifting collector interest, so treat this as a snapshot rather than permanent classification.</p>

<h2>The Rarity Tier System Explained</h2>
<p>The amiibo community uses a four-tier classification system inherited from early shortage discussions on Reddit's r/amiibo subreddit in 2015:</p>

<ul>
    <li><strong>Tier 1 - Unicorn:</strong> Extremely rare, discontinued, commanding $80-$300+ on secondary markets</li>
    <li><strong>Tier 2 - Rare:</strong> Hard to find at retail, regional exclusives, typically $30-$80</li>
    <li><strong>Tier 3 - Uncommon:</strong> Sporadic retail availability, occasional restocks, $20-$35</li>
    <li><strong>Tier 4 - Common:</strong> Readily available at MSRP ($15.99 for figures, $5.99 for cards), often restocked</li>
</ul>

<p>Prices reflect "New in Box" (NIB) condition. Out-of-box (OOB) figures typically sell for 30-50% less.</p>

<div style="text-align: center; margin: 2rem 0;">
    <img src="{% static 'images/blog/rare-amiibo-collection.jpg' %}"
         alt="Rare amiibo figures in protective display cases"
         style="max-width: 100%; height: auto; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.3);">
    <p style="font-size: 0.9rem; color: rgba(253, 247, 227, 0.7); margin-top: 0.5rem; font-style: italic;">Rare amiibo command premium prices on secondary markets</p>
</div>

<h2>Tier 1: Unicorn Status</h2>
<p>Unicorn amiibo represent the holy grail of collecting—figures so rare that finding them at reasonable prices requires patience, luck, and often significant financial investment.</p>

<h3>Gold Mega Man (2016)</h3>
<p><strong>Original Release:</strong> May 20, 2016 (Best Buy exclusive, North America)</p>
<p><strong>Current Market Value:</strong> $150-$250 NIB</p>
<p>Released as a Best Buy exclusive to celebrate Mega Man's legacy, Gold Mega Man suffered from extremely limited production. Best Buy allocated roughly 2-4 units per store, and online stock sold out in under 10 minutes. Many collectors never saw one in person. In 2026, this remains one of the most expensive non-custom amiibo.</p>

<h3>Qbby (BoxBoy! Series, 2017)</h3>
<p><strong>Original Release:</strong> July 2017 (Japan exclusive)</p>
<p><strong>Current Market Value:</strong> $180-$280 NIB</p>
<p>Qbby, the protagonist of HAL Laboratory's BoxBoy! series, received an amiibo release exclusively in Japan with no Western release. Limited print runs combined with obscure character recognition made this figure rare even in Japan. Importing Qbby in 2026 requires international sellers or specialty import shops, often with inflated shipping costs.</p>

<h3>Mega Yarn Yoshi (2015)</h3>
<p><strong>Original Release:</strong> November 2015</p>
<p><strong>Current Market Value:</strong> $120-$200 NIB</p>
<p>The oversized yarn Yoshi amiibo (measuring approximately 8 inches tall) was produced in limited quantities and exclusively sold at select retailers. Its unique yarn construction and large size made it expensive to manufacture ($39.99 MSRP), leading to lower production numbers. Many mint-condition boxes have deteriorated over 11 years, making pristine NIB specimens especially valuable.</p>

<h3>Player 2 Corrin (2018)</h3>
<p><strong>Original Release:</strong> February 2018 (Amazon exclusive)</p>
<p><strong>Current Market Value:</strong> $100-$160 NIB</p>
<p>The female version of Fire Emblem Fates' Corrin was released as an Amazon exclusive with minimal promotion. Many collectors didn't realize it launched until it sold out. Nintendo never restocked Player 2 Corrin, and the character's niche fanbase keeps demand steady.</p>

<h3>Wedding Mario, Peach, and Bowser (2017)</h3>
<p><strong>Original Release:</strong> June 2017 (Japan and Europe only)</p>
<p><strong>Current Market Value:</strong> $80-$140 each NIB</p>
<p>Released to coincide with Super Mario Odyssey's wedding-themed levels, these three figures were never officially sold in North America. Collectors who wanted them had to import from Europe or Japan, leading to permanent scarcity in the US market. In 2026, complete wedding sets (all three figures) sell for $300+.</p>

<h2>Tier 2: Rare Amiibo</h2>
<p>Rare amiibo are difficult to find at retail but not impossible. They typically require hunting through multiple stores, checking online restocks, or paying moderate premiums on secondary markets.</p>

<h3>Original Holy Trinity (Restocked but Rare)</h3>
<ul>
    <li><strong>Marth (2014):</strong> $35-$60 NIB - While restocked several times, demand from Fire Emblem fans keeps this figure scarce</li>
    <li><strong>Villager (2014):</strong> $40-$65 NIB - The original run with large forehead is especially valuable ($80+)</li>
    <li><strong>Wii Fit Trainer (2014):</strong> $30-$55 NIB - Niche character with infrequent restocks</li>
</ul>

<h3>Sanrio Collaboration Cards (2021 Reprint)</h3>
<p><strong>Market Value:</strong> $40-$80 per pack NIB</p>
<p>Despite a March 2021 restock, Sanrio amiibo cards remain rare due to overwhelming demand from Animal Crossing players seeking exclusive furniture sets. Scalpers bought massive quantities during restocks, driving secondary market prices to 3-5x MSRP ($5.99 retail). Individual cards from opened packs sell for $8-$15 each.</p>

<h3>Twilight Princess Link and Zelda (2016)</h3>
<p><strong>Market Value:</strong> $50-$90 each NIB</p>
<p>Released alongside The Legend of Zelda: Twilight Princess HD for Wii U, these figures had modest production runs. Twilight Princess's devoted fanbase ensures consistent demand, while Nintendo has not restocked them since 2017.</p>

<h3>Splatoon 2 Alternate Colors (2017)</h3>
<p><strong>Market Value:</strong> $35-$70 each NIB</p>
<p>Neon Pink Inkling Girl, Neon Green Inkling Boy, and Neon Purple Inkling Squid variants from Splatoon 2's launch are harder to find than standard colors. These were produced in lower quantities to incentivize collectors to purchase multiple versions.</p>

<h2>Tier 3: Uncommon Amiibo</h2>
<p>Uncommon amiibo appear sporadically at major retailers, with occasional restocks keeping them accessible but not abundant.</p>

<h3>Most Super Smash Bros. Series Fighters</h3>
<p>Characters like Captain Falcon, Little Mac, Lucario, Robin, and Ike see periodic restocks but sell out within weeks. Patient collectors can usually find them at MSRP with diligent checking of Best Buy, GameStop, and Amazon.</p>

<h3>Breath of the Wild Champions (2017)</h3>
<p>Mipha, Daruk, Revali, and Urbosa amiibo from BOTW had decent production runs but remain popular among Zelda fans. They're restocked annually but sell out quickly, placing them in uncommon territory.</p>

<h3>Detective Pikachu (2019)</h3>
<p>The large Detective Pikachu amiibo (similar to Mega Yarn Yoshi in size) had moderate production. While not rare, it's harder to find than standard Pikachu figures due to its specialty status.</p>

<h2>Tier 4: Common Amiibo</h2>
<p>Common amiibo are readily available at most retailers carrying Nintendo products.</p>

<h3>Always Available</h3>
<ul>
    <li><strong>Mario (any series):</strong> Nintendo's mascot never goes out of stock for long</li>
    <li><strong>Link (most variants):</strong> Breath of the Wild and Tears of the Kingdom Links are perpetually restocked</li>
    <li><strong>Pikachu:</strong> The Pokémon Company ensures Pikachu amiibo availability</li>
    <li><strong>Kirby:</strong> HAL Laboratory's pink puffball maintains consistent retail presence</li>
    <li><strong>Inkling Boy/Girl (standard colors):</strong> Splatoon's mascots are regularly restocked</li>
</ul>

<h2>2026 Market Trends</h2>

<h3>Rising Stars</h3>
<p>Several previously common amiibo have become uncommon or rare in 2026:</p>
<ul>
    <li><strong>Samus (Metroid Dread):</strong> Spiked in value as Metroid Prime 4 hype builds</li>
    <li><strong>Byleth (Fire Emblem):</strong> Three Houses' enduring popularity increased demand</li>
    <li><strong>Shovel Knight:</strong> Third-party amiibo with no restocks since 2018</li>
</ul>

<h3>Falling Stars</h3>
<p>Some rare amiibo have become more common due to restocks:</p>
<ul>
    <li><strong>King K. Rool:</strong> Once rare, now uncommon thanks to 2025 restock</li>
    <li><strong>Isabelle (Smash):</strong> Summer 2025 restock improved availability</li>
</ul>

<h2>How to Spot Counterfeits</h2>
<p>As amiibo values rise, counterfeit figures flood online marketplaces. Here's how to verify authenticity:</p>

<h3>Packaging Red Flags</h3>
<ul>
    <li><strong>Blurry Logos:</strong> Authentic amiibo have crisp, high-resolution Nintendo logos</li>
    <li><strong>Misspellings:</strong> Check for typos in product names or copyright text</li>
    <li><strong>Wrong Fonts:</strong> Nintendo uses specific fonts; counterfeits often substitute similar but incorrect typefaces</li>
    <li><strong>Incorrect UPC Codes:</strong> Research the correct UPC for each amiibo and compare</li>
</ul>

<h3>Figure Red Flags</h3>
<ul>
    <li><strong>Paint Quality:</strong> Authentic amiibo have clean, precise paint applications; fakes show bleeding or smudging</li>
    <li><strong>Plastic Quality:</strong> Official figures use high-grade plastics; counterfeits feel cheaper and lighter</li>
    <li><strong>NFC Functionality:</strong> While most fakes work functionally, some use incorrect NFC chips that fail to scan</li>
    <li><strong>Base Design:</strong> Study photos of authentic bases; counterfeits often have slightly wrong colors or logo placements</li>
</ul>

<p style="font-size: 1.15rem; color: var(--saffron); margin: 1.5rem 0;">Pro tip: Buy from reputable sellers with return policies. If a "unicorn" amiibo is listed at half its market value, it's likely counterfeit.</p>

<h2>Where to Buy Rare Amiibo Safely</h2>
<ul>
    <li><strong>Amazon (fulfilled by Amazon):</strong> Easier returns if you receive counterfeits</li>
    <li><strong>eBay (check seller ratings):</strong> Look for 99%+ positive feedback and established accounts</li>
    <li><strong>Facebook Marketplace/Local Pickup:</strong> Inspect in person before purchasing</li>
    <li><strong>r/amiiboSwap (Reddit):</strong> Community-vetted trading with reputation systems</li>
    <li><strong>Specialty Retailers:</strong> GameStop, Best Buy, and Target restock rare amiibo occasionally</li>
</ul>

<h2>Collecting Strategies</h2>

<h3>The Patient Collector</h3>
<p>Check retailer websites regularly for restocks (GameStop, Best Buy, Target, Amazon). Most "rare" amiibo get restocked eventually, allowing you to buy at MSRP instead of paying premiums. Nintendo's official website and store pages often announce upcoming releases.</p>

<h3>The Completionist</h3>
<p>Budget $2,000-$5,000 to complete a full NIB collection as of 2026, accounting for unicorns and rare figures. Prioritize unicorns first, as their prices only increase over time.</p>

<h3>The Functional Collector</h3>
<p>If you only care about NFC functionality, buy OOB figures at 30-50% discounts. Rarity matters far less when boxes aren't a concern.</p>

<h2>Conclusion</h2>
<p>Amiibo rarity in 2026 reflects a decade of production decisions, collector demand, and Nintendo's unpredictable restock patterns. While unicorn status figures command premium prices, patient collectors can build impressive collections by tracking restocks and prioritizing must-haves. Remember: rarity fluctuates, so today's uncommon amiibo might be tomorrow's unicorn—or vice versa. Collect what you love, not just what's rare, and your collection will bring joy regardless of market trends.</p>
""",
    },
    {
        "slug": "amiibo-condition-grading-guide",
        "title": "Amiibo Condition Grading: Collector's Guide to NIB, Mint, and Display Quality",
        "date": "2026-02-10",
        "excerpt": "Master amiibo condition grading with this definitive guide covering NIB vs OOB, grading scales, regional differences, and preservation techniques.",
        "content": """
<h2>Why Condition Matters in Amiibo Collecting</h2>
<p>In the world of collectible toys, condition is everything. A mint-condition "unicorn" amiibo can sell for triple the price of the same figure with damaged packaging, while out-of-box figures trade at steep discounts compared to their sealed counterparts. For amiibo collectors, understanding condition grading is essential whether you're building a pristine new-in-box (NIB) showcase, hunting for budget OOB deals, or evaluating secondhand purchases.</p>

<p>Unlike graded trading cards or sealed video games, amiibo lack a formalized professional grading system like PSA or VGA. Instead, the community relies on standardized terminology and visual assessment to determine condition. This guide provides the framework collectors use to evaluate, price, and preserve their amiibo collections.</p>

<h2>NIB vs OOB: The Fundamental Split</h2>

<h3>New in Box (NIB)</h3>
<p>NIB amiibo remain sealed in their original retail packaging, with the figure visible through the plastic window. NIB collectors prioritize:</p>
<ul>
    <li><strong>Investment Potential:</strong> NIB figures retain and appreciate in value more than opened ones</li>
    <li><strong>Display Aesthetics:</strong> Uniform boxes create visually appealing wall or shelf displays</li>
    <li><strong>Preservation:</strong> Sealed packaging protects figures from dust, UV damage, and handling wear</li>
    <li><strong>Completeness:</strong> Guarantees all components (figure, base, packaging) are present and unmodified</li>
</ul>

<p>However, NIB collecting has drawbacks: you cannot inspect the figure closely for paint defects without opening, and boxes require significant display space (each amiibo box measures approximately 7" x 5.5" x 3").</p>

<div style="text-align: center; margin: 2rem 0;">
    <img src="{% static 'images/blog/nib-vs-oob-comparison.jpg' %}"
         alt="Side by side comparison of NIB and OOB amiibo"
         style="max-width: 100%; height: auto; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.3);">
    <p style="font-size: 0.9rem; color: rgba(253, 247, 227, 0.7); margin-top: 0.5rem; font-style: italic;">NIB (left) vs OOB (right) - condition affects value significantly</p>
</div>

<h3>Out of Box (OOB)</h3>
<p>OOB collectors remove figures from packaging to display them freely or use their NFC functionality. OOB collecting offers:</p>
<ul>
    <li><strong>Cost Savings:</strong> OOB figures sell for 30-50% less than NIB equivalents</li>
    <li><strong>Space Efficiency:</strong> Figures without boxes require less shelf space, allowing denser displays</li>
    <li><strong>Full Appreciation:</strong> View figures from all angles, appreciate sculpting details, and handle them</li>
    <li><strong>Functional Use:</strong> Scan them in games without worrying about decreasing value</li>
</ul>

<p>The trade-off: OOB figures rarely appreciate in value and are more vulnerable to damage, dust accumulation, and paint wear over time.</p>

<h2>NIB Grading Scale: From Mint to Poor</h2>
<p>NIB condition is evaluated based on packaging integrity, figure condition (visible through plastic), and overall presentation. The community uses a six-tier scale:</p>

<h3>Mint / Pristine (10/10)</h3>
<p><strong>Description:</strong> Flawless condition with zero defects.</p>
<p><strong>Characteristics:</strong></p>
<ul>
    <li>Packaging has no creases, dents, scratches, or discoloration</li>
    <li>Plastic window is crystal clear with no scuffs or cloudiness</li>
    <li>Figure inside shows perfect paint application with no smudges or missing details</li>
    <li>Price sticker never applied (or removed perfectly with no residue)</li>
    <li>Cardboard backing is crisp with sharp corners</li>
</ul>
<p><strong>Market Impact:</strong> Commands full market value or premium for rare figures. Serious collectors pay extra for mint specimens.</p>

<h3>Near Mint (8-9/10)</h3>
<p><strong>Description:</strong> Excellent condition with only minor, barely noticeable imperfections.</p>
<p><strong>Acceptable Flaws:</strong></p>
<ul>
    <li>Tiny corner ding on cardboard (less than 2mm)</li>
    <li>Slight shelf wear on edges</li>
    <li>Minor packaging glue residue (not on visible display side)</li>
    <li>Small price sticker residue on back or bottom (not front)</li>
</ul>
<p><strong>Market Impact:</strong> 90-95% of mint value. Most collectors consider near mint acceptable for display-grade collections.</p>

<h3>Very Good (6-7/10)</h3>
<p><strong>Description:</strong> Noticeable but not severe damage to packaging.</p>
<p><strong>Common Issues:</strong></p>
<ul>
    <li>Visible creases on cardboard backing</li>
    <li>Multiple corner dings or edge wear</li>
    <li>Light scratches on plastic window</li>
    <li>Price sticker on front that left residue after removal</li>
    <li>Minor discoloration on white areas of packaging</li>
</ul>
<p><strong>Market Impact:</strong> 70-85% of mint value. Acceptable for functional collectors who want sealed figures but don't prioritize pristine packaging.</p>

<h3>Good (4-5/10)</h3>
<p><strong>Description:</strong> Significant packaging damage but figure remains sealed and protected.</p>
<p><strong>Typical Damage:</strong></p>
<ul>
    <li>Crushed corners or moderate box warping</li>
    <li>Cloudy or scratched plastic window obscuring figure details</li>
    <li>Torn cardboard (but not fully separated)</li>
    <li>Noticeable sun fading or discoloration</li>
    <li>Tape residue or sticker remnants on display side</li>
</ul>
<p><strong>Market Impact:</strong> 50-65% of mint value. Often purchased by collectors who plan to open them anyway or use them functionally.</p>

<h3>Fair (2-3/10)</h3>
<p><strong>Description:</strong> Heavy damage to packaging, possibly affecting figure protection.</p>
<p><strong>Severe Issues:</strong></p>
<ul>
    <li>Partially detached cardboard backing</li>
    <li>Broken plastic window or tears exposing figure</li>
    <li>Water damage or mold on packaging</li>
    <li>Crushed box significantly affecting shape</li>
    <li>Figure inside shows visible paint defects or damage</li>
</ul>
<p><strong>Market Impact:</strong> 30-45% of mint value. Only valuable if the figure itself is rare; packaging is essentially worthless.</p>

<h3>Poor (1/10)</h3>
<p><strong>Description:</strong> Packaging is destroyed or missing major components.</p>
<p><strong>Conditions:</strong></p>
<ul>
    <li>Cardboard backing completely separated or missing</li>
    <li>Plastic torn or removed</li>
    <li>Packaging pieces lost</li>
    <li>Figure may be damaged or have missing components</li>
</ul>
<p><strong>Market Impact:</strong> Equivalent to OOB pricing. The "NIB" designation no longer applies.</p>

<p style="font-size: 1.15rem; color: var(--saffron); margin: 1.5rem 0;">Grading tip: When photographing for sale, show all six sides of the package plus close-ups of any damage. Transparency prevents disputes.</p>

<h2>OOB Grading Scale</h2>
<p>Out-of-box figures are graded primarily on figure condition, as packaging is discarded or irrelevant.</p>

<h3>OOB Mint (10/10)</h3>
<ul>
    <li>Figure looks factory fresh with perfect paint</li>
    <li>No scratches, scuffs, or discoloration</li>
    <li>Base is pristine with no wear on NFC symbol or feet</li>
    <li>No dust accumulation</li>
</ul>

<h3>OOB Near Mint (8-9/10)</h3>
<ul>
    <li>Minor dust that can be cleaned</li>
    <li>Barely visible micro-scratches on base</li>
    <li>Tiny paint imperfections (often factory defects)</li>
</ul>

<h3>OOB Very Good (6-7/10)</h3>
<ul>
    <li>Noticeable scratches or scuffs on figure or base</li>
    <li>Minor paint chips (less than 2mm)</li>
    <li>Slight yellowing or discoloration from UV exposure</li>
</ul>

<h3>OOB Good (4-5/10)</h3>
<ul>
    <li>Multiple paint chips or scratches</li>
    <li>Visible discoloration or fading</li>
    <li>Minor structural damage (loose joints, bent parts)</li>
</ul>

<h3>OOB Fair/Poor (1-3/10)</h3>
<ul>
    <li>Major paint loss or damage</li>
    <li>Broken components</li>
    <li>Non-functional NFC chip</li>
</ul>

<h2>Regional Packaging Differences</h2>
<p>Amiibo packaging varies by region, which affects both collectibility and grading considerations:</p>

<h3>North American (USA/Canada)</h3>
<ul>
    <li><strong>Text:</strong> English and French (bilingual packaging required in Canada)</li>
    <li><strong>Rating:</strong> ESRB ratings on some game-specific amiibo</li>
    <li><strong>UPC:</strong> Standard 12-digit UPC barcode</li>
    <li><strong>Collectibility:</strong> Most common in Western markets; typically valued equally to other regions unless specifically seeking NA variants</li>
</ul>

<h3>European (EU/UK)</h3>
<ul>
    <li><strong>Text:</strong> Multilingual (often 5+ languages on back)</li>
    <li><strong>Rating:</strong> PEGI rating system</li>
    <li><strong>Barcode:</strong> EAN-13 barcode</li>
    <li><strong>Collectibility:</strong> Some exclusive releases never came to North America (Wedding Mario set), making EU packaging valuable to NA collectors</li>
</ul>

<h3>Japanese</h3>
<ul>
    <li><strong>Text:</strong> Predominantly Japanese with some English</li>
    <li><strong>Barcode:</strong> JAN barcode</li>
    <li><strong>Design:</strong> Often features alternate artwork or color schemes</li>
    <li><strong>Collectibility:</strong> Highly sought by Western collectors for "cleaner" packaging (less regulatory text) and exclusives like Qbby</li>
</ul>

<h3>Australian</h3>
<ul>
    <li><strong>Text:</strong> English</li>
    <li><strong>Rating:</strong> ACB (Australian Classification Board) ratings</li>
    <li><strong>Collectibility:</strong> Less common internationally; mild premium for collectors seeking all regional variants</li>
</ul>

<p><strong>Condition Note:</strong> When grading regional variants, assess condition by the same criteria, but note that import packaging may show additional wear from international shipping.</p>

<h2>Storage and Preservation Best Practices</h2>

<h3>NIB Storage</h3>
<ul>
    <li><strong>Display Shelves:</strong> Use deep shelves (6+ inches) to accommodate box depth</li>
    <li><strong>UV Protection:</strong> Keep away from direct sunlight; UV rays cause cardboard yellowing and plastic cloudiness</li>
    <li><strong>Humidity Control:</strong> Maintain 30-50% humidity to prevent cardboard warping and mold</li>
    <li><strong>Stacking:</strong> Never stack more than 3 boxes high; weight crushes bottom boxes over time</li>
    <li><strong>Protective Cases:</strong> For high-value amiibo, use hard acrylic display cases or "box protectors" (plastic sleeves)</li>
</ul>

<h3>OOB Storage</h3>
<ul>
    <li><strong>Display Cases:</strong> Glass-front cases (like IKEA DETOLF) prevent dust while allowing visibility</li>
    <li><strong>Cleaning:</strong> Use soft microfiber cloths for dusting; avoid harsh chemicals that strip paint</li>
    <li><strong>Spacing:</strong> Avoid overcrowding; figures touching can cause paint transfer</li>
    <li><strong>Bases:</strong> Keep original bases; some collectors display figures on custom risers but store bases separately</li>
</ul>

<h3>Long-Term Archival</h3>
<p>For collectors storing amiibo long-term (5+ years) without displaying:</p>
<ul>
    <li>Use acid-free boxes or plastic bins with silica gel packets (controls moisture)</li>
    <li>Store in climate-controlled spaces (not attics or basements prone to temperature/humidity swings)</li>
    <li>Photograph each figure before storage for insurance purposes</li>
    <li>Inventory all stored amiibo with photos and notes on condition</li>
</ul>

<h2>Buying and Selling Considerations</h2>

<h3>When Buying</h3>
<ul>
    <li><strong>Request Multiple Photos:</strong> Ask sellers for photos of all sides and any damage, even if not visible in listings</li>
    <li><strong>Ask About Smoke/Pets:</strong> Tobacco smoke and pet odors can permeate cardboard and are nearly impossible to remove</li>
    <li><strong>Inspect in Person When Possible:</strong> Online photos can hide cloudiness, discoloration, and creasing</li>
    <li><strong>Check NFC Functionality:</strong> For OOB purchases, ensure the NFC chip still scans (some counterfeits have non-functional chips)</li>
</ul>

<h3>When Selling</h3>
<ul>
    <li><strong>Honest Grading:</strong> Overgrading leads to returns and negative feedback; err on the side of caution</li>
    <li><strong>Detailed Listings:</strong> Photograph every angle and describe all flaws explicitly</li>
    <li><strong>Package Carefully:</strong> Use bubble wrap, cardboard reinforcement, and "Fragile" labels; poor shipping can downgrade mint to good</li>
    <li><strong>Price Appropriately:</strong> Use eBay sold listings and r/amiibo price guides to set realistic prices based on condition</li>
</ul>

<h2>Common Condition Issues and How to Address Them</h2>

<h3>Sun Fading</h3>
<p><strong>Problem:</strong> Cardboard yellows, colors fade</p>
<p><strong>Prevention:</strong> Store away from windows; use UV-protective glass or acrylic</p>
<p><strong>Fix:</strong> Irreversible; cannot restore faded packaging</p>

<h3>Shelf Wear</h3>
<p><strong>Problem:</strong> Edges and corners show whitening or fraying from friction</p>
<p><strong>Prevention:</strong> Use protective sleeves or space boxes to avoid rubbing</p>
<p><strong>Fix:</strong> Touch-up markers can color minor whitening, but it's visible upon close inspection</p>

<h3>Cloudy Plastic Windows</h3>
<p><strong>Problem:</strong> Plastic yellows or becomes opaque over time</p>
<p><strong>Prevention:</strong> Keep away from heat sources and sunlight</p>
<p><strong>Fix:</strong> Try mild plastic polish (like Novus), but results vary</p>

<h3>Paint Defects (Factory)</h3>
<p><strong>Problem:</strong> Smudges, missing paint, overspray on NIB figures</p>
<p><strong>Note:</strong> Factory defects are not the seller's fault; inspect before purchase</p>
<p><strong>Fix for OOB:</strong> Skilled painters can touch up figures, but this decreases value for resale</p>

<h2>Conclusion</h2>
<p>Condition grading is the cornerstone of informed amiibo collecting. Whether you're building a pristine NIB shrine to Nintendo's finest characters or curating a functional OOB display, understanding how to assess, preserve, and value condition ensures your collection retains its worth and brings lasting enjoyment. Remember: the "right" condition is whatever matches your collecting goals—there's no wrong way to enjoy amiibo, whether mint in box or lovingly displayed out of package.</p>
""",
    },
    {
        "slug": "custom-amiibo-painting-guide",
        "title": "Custom Amiibo Painting Guide: Techniques, Materials, and Inspiration",
        "date": "2026-02-10",
        "excerpt": "Transform ordinary amiibo into unique masterpieces with this comprehensive custom painting guide covering materials, techniques, and safety tips.",
        "content": """
<h2>Introduction to Custom Amiibo</h2>
<p>The custom amiibo community represents one of the most creative corners of Nintendo fandom. Since amiibo launched in 2014, talented artists have transformed mass-produced figures into one-of-a-kind sculptures featuring alternate costumes, crossover characters, and original designs. Whether you want to create a gold-plated Link, repaint Isabelle in your favorite villager's color scheme, or sculpt entirely new details onto existing figures, custom amiibo work offers endless creative possibilities.</p>

<p>This guide walks you through the complete process of custom amiibo creation, from selecting your first figure to applying the final protective coating. While the learning curve can be steep, even beginners can produce impressive results with patience, proper materials, and attention to detail.</p>

<p style="font-size: 1.15rem; color: var(--saffron); margin: 1.5rem 0;">Important: Custom amiibo retain full NFC functionality. The chip in the base is unaffected by paint or modifications to the figure itself.</p>

<h2>Choosing Your First Figure</h2>

<h3>Best Figures for Beginners</h3>
<p>Not all amiibo are equally suited for customization. Beginners should start with figures that have:</p>
<ul>
    <li><strong>Simple Shapes:</strong> Avoid figures with intricate details or many small parts (like Fire Emblem characters with complex armor)</li>
    <li><strong>Smooth Surfaces:</strong> Figures with less texture are easier to repaint cleanly</li>
    <li><strong>Common Availability:</strong> Practice on inexpensive, readily available figures before attempting rare ones</li>
    <li><strong>Fewer Colors:</strong> Characters with simple color schemes reduce complexity</li>
</ul>

<p><strong>Recommended Starter Figures:</strong></p>
<ul>
    <li><strong>Kirby:</strong> Round, smooth, monochromatic—perfect for learning paint application</li>
    <li><strong>Yoshi:</strong> Simple shapes, large surface area, forgiving sculpt</li>
    <li><strong>Toon Link:</strong> Cartoony proportions and clear color separation</li>
    <li><strong>Mario:</strong> Inexpensive, readily available, iconic design</li>
</ul>

<p><strong>Avoid for Beginners:</strong></p>
<ul>
    <li>Smash Bros. characters with complex weapons (Byleth, Pyra/Mythra)</li>
    <li>Figures with translucent parts (Guardian, Ice Climbers)</li>
    <li>Rare or expensive amiibo (save these for when you're experienced)</li>
</ul>

<div style="text-align: center; margin: 2rem 0;">
    <img src="{% static 'images/blog/custom-painted-amiibo.jpg' %}"
         alt="Custom painted amiibo with unique colors and details"
         style="max-width: 100%; height: auto; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.3);">
    <p style="font-size: 0.9rem; color: rgba(253, 247, 227, 0.7); margin-top: 0.5rem; font-style: italic;">Custom amiibo transform figures into unique art pieces</p>
</div>

<h2>Essential Materials and Tools</h2>

<h3>Paint</h3>
<p><strong>Acrylic Paints (Recommended):</strong></p>
<ul>
    <li><strong>Brands:</strong> Vallejo Model Color, Citadel (Games Workshop), Army Painter</li>
    <li><strong>Why Acrylic:</strong> Water-based, non-toxic, dries quickly, available in hundreds of colors</li>
    <li><strong>Cost:</strong> $3-5 per 17ml bottle; starter sets run $30-50 for 10-12 essential colors</li>
</ul>

<p><strong>Must-Have Colors:</strong></p>
<ul>
    <li>White (for mixing lighter tones and highlighting)</li>
    <li>Black (for mixing darker tones and lining)</li>
    <li>Primary colors (red, blue, yellow) for custom mixing</li>
    <li>Flesh tones (if painting faces)</li>
    <li>Metallics (gold, silver, bronze) for accents</li>
</ul>

<h3>Primer</h3>
<p><strong>Purpose:</strong> Primer creates a surface that paint adheres to, preventing chipping and ensuring even coverage.</p>
<p><strong>Recommended Primers:</strong></p>
<ul>
    <li><strong>Citadel Chaos Black or Corax White Spray Primer:</strong> $17-20 per can, high-quality, designed for miniatures</li>
    <li><strong>Army Painter Primer:</strong> $15-18 per can, similar quality to Citadel</li>
    <li><strong>Krylon ColorMaster Primer:</strong> $5-8 per can, budget option (test on scrap plastic first)</li>
</ul>

<p><strong>Color Choice:</strong> Use white primer for light-colored figures, black for dark figures, gray for neutral starts.</p>

<h3>Brushes</h3>
<p>Invest in quality brushes—cheap brushes shed bristles and leave streaks.</p>
<ul>
    <li><strong>Size 0 or 00:</strong> Fine detail work (eyes, lines, tiny details)</li>
    <li><strong>Size 1 or 2:</strong> General painting (most of the figure)</li>
    <li><strong>Size 4 or 5:</strong> Large areas (base coats, backgrounds)</li>
    <li><strong>Recommended Brands:</strong> Winsor & Newton Series 7, Raphael 8404, or Army Painter Wargamer brushes</li>
    <li><strong>Cost:</strong> $5-20 per brush depending on quality; a basic set costs $20-40</li>
</ul>

<h3>Sealant/Varnish</h3>
<p><strong>Purpose:</strong> Protects finished paint work from chipping, scratching, and UV damage.</p>
<p><strong>Options:</strong></p>
<ul>
    <li><strong>Testors Dullcote Spray:</strong> Matte finish, professional favorite, $10-12 per can</li>
    <li><strong>Citadel 'Ardcoat or Munitorum Varnish:</strong> Brush-on option for targeted gloss or matte, $5-7 per pot</li>
    <li><strong>Krylon Matte Finish:</strong> Budget spray option, $7-10 per can</li>
</ul>

<p><strong>Finish Types:</strong> Matte (no shine), satin (slight shine), gloss (high shine). Most custom amiibo use matte for a realistic look.</p>

<h3>Additional Supplies</h3>
<ul>
    <li><strong>Isopropyl Alcohol (90%+):</strong> For cleaning figures before priming, $3-5 per bottle</li>
    <li><strong>Painter's Tape or Blu-Tack:</strong> To mask areas you don't want painted</li>
    <li><strong>Palette:</strong> Wet palette (keeps paint moist) or disposable palette paper, $10-20</li>
    <li><strong>Water Cups:</strong> Two cups (one for rinsing, one for clean water)</li>
    <li><strong>Paper Towels:</strong> For brush drying and cleanup</li>
    <li><strong>Fine Sandpaper (400-600 grit):</strong> For smoothing surfaces or removing factory paint, $3-5</li>
    <li><strong>X-Acto Knife:</strong> For separating figure from base or removing mold lines, $5-10</li>
    <li><strong>Super Glue (cyanoacrylate):</strong> For reattaching parts after painting, $3-5</li>
</ul>

<h2>Preparation Process</h2>

<h3>Step 1: Disassembly</h3>
<p>Many amiibo can be carefully separated from their bases to make painting easier. The NFC chip is in the base, so the figure itself is just plastic.</p>
<ul>
    <li><strong>Method:</strong> Gently heat the connection point with a hairdryer on low heat for 30-60 seconds</li>
    <li><strong>Twist:</strong> Slowly twist and pull the figure from the base (some force may be needed)</li>
    <li><strong>Caution:</strong> Some figures are glued very securely; forcing them may break pegs</li>
</ul>

<p>Alternatively, leave the figure attached and carefully tape off the base before painting.</p>

<h3>Step 2: Cleaning</h3>
<p>Factory amiibo may have mold release agents or oils that prevent paint adhesion.</p>
<ul>
    <li>Scrub the figure gently with a toothbrush dipped in 90%+ isopropyl alcohol</li>
    <li>Rinse with water and let dry completely (1-2 hours)</li>
</ul>

<h3>Step 3: Surface Preparation</h3>
<p>If repainting over existing paint:</p>
<ul>
    <li><strong>Option A (Recommended):</strong> Lightly sand the surface with 400-600 grit sandpaper to create texture for primer</li>
    <li><strong>Option B (Advanced):</strong> Strip factory paint using acetone or Simple Green (soak 24 hours, scrub with toothbrush)</li>
</ul>

<h3>Step 4: Priming</h3>
<p>Priming is non-negotiable for durable custom work.</p>
<ul>
    <li><strong>Environment:</strong> Spray outdoors or in a well-ventilated area, ideally 60-75°F with low humidity</li>
    <li><strong>Technique:</strong> Hold spray can 6-8 inches away, use short bursts (1-2 seconds), multiple thin coats rather than one thick coat</li>
    <li><strong>Drying:</strong> Wait 30 minutes between coats; fully cure for 24 hours before painting</li>
    <li><strong>Coverage:</strong> 2-3 light coats should cover evenly without obscuring details</li>
</ul>

<p style="font-size: 1.15rem; color: var(--saffron); margin: 1.5rem 0;">Critical mistake to avoid: Over-priming fills in sculpt details. Always use thin coats.</p>

<h2>Painting Techniques</h2>

<h3>Base Coating</h3>
<p>Apply the primary colors to establish your design.</p>
<ul>
    <li><strong>Thin Your Paint:</strong> Add 10-20% water to acrylic paint for smoother application</li>
    <li><strong>Multiple Coats:</strong> 2-3 thin coats provide better coverage than one thick coat</li>
    <li><strong>Brush Technique:</strong> Use smooth, even strokes in one direction; avoid back-and-forth scrubbing</li>
    <li><strong>Drying Time:</strong> Wait 15-30 minutes between coats</li>
</ul>

<h3>Detail Work</h3>
<p>Adding fine details like eyes, lines, and accents.</p>
<ul>
    <li><strong>Steady Hand:</strong> Rest your wrist on a stable surface; brace your painting hand with your other hand</li>
    <li><strong>Thin Paint:</strong> Details require very thin paint; add more water than for base coats</li>
    <li><strong>Fine Brushes:</strong> Use size 0 or 00 brushes</li>
    <li><strong>Patience:</strong> Rush-free detail work is essential; take breaks to avoid fatigue</li>
</ul>

<h3>Shading and Highlighting</h3>
<p>Advanced techniques that add depth and dimension.</p>

<p><strong>Shading (Washes):</strong></p>
<ul>
    <li>Dilute dark paint (black or dark brown) with 70-80% water</li>
    <li>Apply to recessed areas (folds, crevices); capillary action draws wash into details</li>
    <li>Let dry completely; adds realistic shadows</li>
</ul>

<p><strong>Highlighting (Drybrushing):</strong></p>
<ul>
    <li>Dip brush in light color, wipe most paint off on paper towel</li>
    <li>Lightly brush over raised areas; paint catches on edges</li>
    <li>Creates natural highlights and texture</li>
</ul>

<h3>Common Painting Challenges</h3>
<ul>
    <li><strong>Streaks:</strong> Paint too thick or brush too dry; thin paint and use a damp brush</li>
    <li><strong>Brush Marks:</strong> Paint too thick; apply thinner coats</li>
    <li><strong>Coverage Issues:</strong> Wrong primer color; white primer shows through dark paint (use dark primer for dark colors)</li>
    <li><strong>Smudging:</strong> Not waiting long enough between coats; patience is key</li>
</ul>

<h2>Finishing and Reassembly</h2>

<h3>Step 1: Final Inspection</h3>
<p>Examine your work under bright light. Touch up any missed spots or mistakes with a fine brush.</p>

<h3>Step 2: Sealing</h3>
<ul>
    <li>Wait 24 hours after final paint layer before sealing</li>
    <li>Apply 2-3 light coats of varnish spray, waiting 30 minutes between coats</li>
    <li>Hold can 8-10 inches away, use smooth sweeping motions</li>
    <li>Cure for 48 hours before handling extensively</li>
</ul>

<h3>Step 3: Reassembly</h3>
<ul>
    <li>If you separated the figure from the base, reattach using super glue on the peg</li>
    <li>Hold firmly for 30 seconds; let cure for 24 hours before handling</li>
    <li>Test NFC functionality by scanning in a compatible game</li>
</ul>

<h2>Safety and Workspace Tips</h2>

<h3>Safety Precautions</h3>
<ul>
    <li><strong>Ventilation:</strong> Always use spray primers and sealants outdoors or with proper ventilation (spray booth or open windows)</li>
    <li><strong>Respirator Mask:</strong> Wear a mask rated for organic vapors when spraying (3M P100 or equivalent)</li>
    <li><strong>Gloves:</strong> Nitrile gloves protect hands from paint and solvents</li>
    <li><strong>Eye Protection:</strong> Safety glasses when spraying or sanding</li>
</ul>

<h3>Workspace Setup</h3>
<ul>
    <li><strong>Good Lighting:</strong> Daylight LED lamps (5000-6500K) show true colors and details</li>
    <li><strong>Protected Surface:</strong> Cover your workspace with newspaper, cardboard, or a silicone mat</li>
    <li><strong>Organization:</strong> Keep paints organized by color; label custom mixes</li>
    <li><strong>Comfortable Seating:</strong> Painting sessions can last 1-3 hours; ergonomic seating prevents fatigue</li>
</ul>

<h2>Inspiration Gallery: Popular Custom Ideas</h2>

<h3>Alternate Costumes</h3>
<ul>
    <li>Mario in different power-up states (Fire Mario, Tanooki Mario, Frog Mario)</li>
    <li>Link in alternate outfits from Breath of the Wild or Tears of the Kingdom</li>
    <li>Samus in various suit designs (Phazon Suit, Gravity Suit, Zero Suit recolors)</li>
</ul>

<h3>Crossover Characters</h3>
<ul>
    <li>Kirby painted as other characters (Meta Knight colors, Dedede colors)</li>
    <li>Inkling in custom gear combinations</li>
    <li>Mario characters in different franchise styles (cel-shaded, realistic, chibi)</li>
</ul>

<h3>Metallic and Special Effects</h3>
<ul>
    <li>Gold or silver chrome finishes (using Molotow chrome markers)</li>
    <li>Weathered/battle-damaged effects (dry brushing, washes)</li>
    <li>Glow-in-the-dark paint accents</li>
</ul>

<h3>Original Characters</h3>
<ul>
    <li>Custom Animal Crossing villagers</li>
    <li>OC Pokémon or fakemon designs</li>
    <li>Mii Fighter designs brought to life</li>
</ul>

<h2>Community and Resources</h2>
<p>Connect with fellow custom amiibo artists:</p>
<ul>
    <li><strong>r/amiibo (Reddit):</strong> "Custom" flair for sharing work and getting feedback</li>
    <li><strong>Instagram:</strong> Search #customamiibo for inspiration and technique examples</li>
    <li><strong>YouTube:</strong> Search "custom amiibo tutorial" for step-by-step video guides</li>
    <li><strong>Online Forums:</strong> Many amiibo collecting communities have dedicated custom sections</li>
</ul>

<h2>Conclusion</h2>
<p>Custom amiibo painting transforms collecting from passive ownership into active creation. While the initial learning curve can be challenging, the satisfaction of holding a truly unique figure—one that exists nowhere else in the world—makes the effort worthwhile. Start with simple repaints, master your materials and techniques, and gradually tackle more ambitious projects. Your first custom may have imperfections, but every figure you paint improves your skills. Most importantly: have fun, experiment boldly, and celebrate the creative spirit that makes the amiibo community so vibrant.</p>
""",
    },
    {
        "slug": "amiibo-display-solutions-guide",
        "title": "The Ultimate Amiibo Display Guide: Shelves, Cases, and Creative Solutions",
        "date": "2026-02-10",
        "excerpt": "Showcase your amiibo collection with style using this comprehensive display guide covering budget-friendly to premium solutions for every collector.",
        "content": """
<h2>Why Display Matters</h2>
<p>You've invested time, money, and passion into building your amiibo collection—whether it's a modest dozen figures or a complete library of 800+ pieces. Proper display transforms a pile of toys into a curated showcase that reflects your dedication while protecting your investment from damage. A well-organized display also makes it easier to track what you own, identify gaps in your collection, and appreciate the artistic detail Nintendo's designers put into each figure.</p>

<p>This guide explores display solutions across every budget, space constraint, and aesthetic preference, from college dorm shelves to dedicated collector rooms.</p>

<div style="text-align: center; margin: 2rem 0;">
    <img src="{% static 'images/blog/amiibo-display-shelf.jpg' %}"
         alt="Organized amiibo display on IKEA shelving"
         style="max-width: 100%; height: auto; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.3);">
    <p style="font-size: 0.9rem; color: rgba(253, 247, 227, 0.7); margin-top: 0.5rem; font-style: italic;">Proper display showcases your collection beautifully</p>
</div>

<h2>Budget-Friendly Solutions ($0-50)</h2>

<h3>IKEA MOSSLANDA Picture Ledge</h3>
<p><strong>Price:</strong> $9.99-14.99 depending on length (23", 30", or 45")</p>
<p><strong>Where to Buy:</strong> <a href="https://www.ikea.com/us/en/cat/picture-ledges-18630/" target="_blank" rel="noopener" style="color: var(--saffron);">IKEA.com</a> or in-store</p>
<p><strong>Capacity:</strong> 12-20 amiibo per shelf (NIB or OOB)</p>
<p><strong>Pros:</strong></p>
<ul>
    <li>Clean, minimalist design that doesn't overpower a room</li>
    <li>Easy wall mounting with included hardware</li>
    <li>Comes in white, black, and natural wood finishes</li>
    <li>Shallow depth (3") keeps amiibo close to wall for space efficiency</li>
    <li>Can be stacked vertically for multi-tier displays</li>
</ul>
<p><strong>Cons:</strong></p>
<ul>
    <li>No protection from dust</li>
    <li>NIB boxes may overhang the edge slightly</li>
    <li>Requires wall mounting (not renter-friendly without permission)</li>
</ul>
<p><strong>Best For:</strong> OOB collectors with limited budgets who want a clean, modern look.</p>

<h3>Floating Cube Shelves</h3>
<p><strong>Price:</strong> $15-30 for a set of 3-5 cubes</p>
<p><strong>Capacity:</strong> 1-4 amiibo per cube depending on size</p>
<p><strong>Pros:</strong></p>
<ul>
    <li>Modular design allows creative arrangements</li>
    <li>Adds visual interest to blank walls</li>
    <li>Available at Target, Walmart, Amazon, and home goods stores</li>
</ul>
<p><strong>Cons:</strong></p>
<ul>
    <li>Low capacity per shelf (better for smaller collections)</li>
    <li>Wall mounting required</li>
</ul>
<p><strong>Best For:</strong> Collectors who want to spotlight favorite figures individually.</p>

<h3>Repurposed Bookshelves</h3>
<p><strong>Price:</strong> $0-50 (use existing furniture or find at thrift stores)</p>
<p><strong>Capacity:</strong> 50-200+ amiibo depending on size</p>
<p><strong>Pros:</strong></p>
<ul>
    <li>No additional purchase if you already own shelving</li>
    <li>Adjustable shelves accommodate NIB boxes or OOB figures</li>
    <li>Can integrate amiibo with books, games, and other collectibles</li>
</ul>
<p><strong>Cons:</strong></p>
<ul>
    <li>No dust protection</li>
    <li>May not be dedicated amiibo space (shared with other items)</li>
    <li>Generic appearance</li>
</ul>
<p><strong>Best For:</strong> Collectors just starting out or working with zero-dollar budgets.</p>

<h3>DIY Cardboard Risers</h3>
<p><strong>Price:</strong> $0-5 (cardboard, tape, optional decorative paper)</p>
<p><strong>Capacity:</strong> Unlimited (custom to your needs)</p>
<p><strong>Pros:</strong></p>
<ul>
    <li>Completely free if using recycled boxes</li>
    <li>Customizable height and width for tiered displays</li>
    <li>Can be covered with decorative paper or painted to match aesthetic</li>
</ul>
<p><strong>Cons:</strong></p>
<ul>
    <li>Not as durable as commercial options</li>
    <li>Requires crafting skills and time</li>
    <li>May look DIY even when decorated</li>
</ul>
<p><strong>Best For:</strong> Budget-conscious collectors with crafting experience.</p>

<h2>Mid-Range Options ($50-200)</h2>

<h3>IKEA DETOLF Glass Cabinet</h3>
<p><strong>Price:</strong> $69.99 (as of 2026)</p>
<p><strong>Where to Buy:</strong> <a href="https://www.ikea.com/us/en/p/detolf-glass-door-cabinet-black-brown-10119206/" target="_blank" rel="noopener" style="color: var(--saffron);">IKEA.com</a> or in-store</p>
<p><strong>Capacity:</strong> 60-80 OOB amiibo (4 shelves)</p>
<p><strong>Pros:</strong></p>
<ul>
    <li>Iconic collector favorite used for figures, anime statues, and collectibles worldwide</li>
    <li>Glass doors protect from dust while maintaining visibility from all sides</li>
    <li>Four adjustable glass shelves</li>
    <li>Slim profile (17" x 17" base, 64" tall) fits in corners or against walls</li>
    <li>Widely available at IKEA stores and online</li>
</ul>
<p><strong>Cons:</strong></p>
<ul>
    <li>Glass shelves can bow under excessive weight (limit 10-15 lbs per shelf)</li>
    <li>Not ideal for NIB collectors (boxes may not fit well on shelves)</li>
    <li>Assembly required (1-2 hours)</li>
    <li>No built-in lighting (must add separately)</li>
</ul>
<p><strong>Best For:</strong> OOB collectors seeking a dust-free, display-quality solution.</p>

<p style="font-size: 1.15rem; color: var(--saffron); margin: 1.5rem 0;">Pro tip: Add LED light strips ($10-20) inside the DETOLF for dramatic lighting effects.</p>

<h3>Baseball Bat Display Cases (Wall-Mounted)</h3>
<p><strong>Price:</strong> $40-80 each</p>
<p><strong>Where to Buy:</strong> <a href="https://www.amazon.com/s?k=baseball+bat+display+case" target="_blank" rel="noopener" style="color: var(--saffron);">Amazon</a>, eBay, or specialty display stores</p>
<p><strong>Capacity:</strong> 15-25 NIB amiibo per case</p>
<p><strong>Pros:</strong></p>
<ul>
    <li>Originally designed for baseballs/bats but perfect for NIB amiibo</li>
    <li>Clear acrylic front provides dust protection</li>
    <li>Wall-mounted saves floor space</li>
    <li>Available on Amazon, eBay, and collectible stores</li>
</ul>
<p><strong>Cons:</strong></p>
<ul>
    <li>Wall mounting required (not renter-friendly)</li>
    <li>Depth may be tight for larger amiibo boxes</li>
    <li>Limited vertical space (usually 4-5 rows max)</li>
</ul>
<p><strong>Best For:</strong> NIB collectors who want wall-mounted, dust-protected displays.</p>

<h3>Rotating Display Tower</h3>
<p><strong>Price:</strong> $60-120</p>
<p><strong>Capacity:</strong> 40-80 OOB amiibo (depending on tiers)</p>
<p><strong>Pros:</strong></p>
<ul>
    <li>Rotates 360° for easy viewing from all angles</li>
    <li>Space-efficient vertical design</li>
    <li>No wall mounting required</li>
    <li>Often includes adjustable shelves</li>
</ul>
<p><strong>Cons:</strong></p>
<ul>
    <li>No dust protection</li>
    <li>Figures may fall during rotation if not secured</li>
    <li>Takes up floor space</li>
</ul>
<p><strong>Best For:</strong> Collectors who want interactive, space-saving displays.</p>

<h3>Michael's Display Cases</h3>
<p><strong>Price:</strong> $50-100 per case</p>
<p><strong>Where to Buy:</strong> <a href="https://www.michaels.com/search?q=display%20case" target="_blank" rel="noopener" style="color: var(--saffron);">Michaels.com</a> or in-store</p>
<p><strong>Capacity:</strong> 10-30 amiibo depending on size</p>
<p><strong>Pros:</strong></p>
<ul>
    <li>Designed specifically for collectibles</li>
    <li>Clear acrylic or glass fronts</li>
    <li>Available in various sizes and styles (wall-mounted, tabletop, standing)</li>
    <li>Frequent sales and coupons (40-50% off)</li>
</ul>
<p><strong>Cons:</strong></p>
<ul>
    <li>More expensive than IKEA options at full price</li>
    <li>Limited availability (US only, select locations)</li>
</ul>
<p><strong>Best For:</strong> Collectors seeking professional display cases with customization options.</p>

<h2>Premium Solutions ($200+)</h2>

<h3>Sora Display Cases</h3>
<p><strong>Price:</strong> $300-600 per case</p>
<p><strong>Capacity:</strong> 100-200 OOB amiibo</p>
<p><strong>Pros:</strong></p>
<ul>
    <li>Museum-quality display cases designed for serious collectors</li>
    <li>Tempered glass construction</li>
    <li>Built-in LED lighting systems</li>
    <li>Lockable doors for security</li>
    <li>Minimalist Japanese design aesthetic</li>
</ul>
<p><strong>Cons:</strong></p>
<ul>
    <li>Very expensive</li>
    <li>Requires professional assembly or significant DIY skill</li>
    <li>Heavy (150+ lbs) and difficult to move once assembled</li>
</ul>
<p><strong>Best For:</strong> Serious collectors with dedicated display rooms and budgets to match.</p>

<h3>Custom Built-In Shelving</h3>
<p><strong>Price:</strong> $500-3,000+ (professional installation)</p>
<p><strong>Capacity:</strong> Unlimited (custom to your space)</p>
<p><strong>Pros:</strong></p>
<ul>
    <li>Perfectly fitted to your room's dimensions</li>
    <li>Can incorporate lighting, backing, and custom features</li>
    <li>Permanent fixture adds value to home</li>
    <li>Professional appearance</li>
</ul>
<p><strong>Cons:</strong></p>
<ul>
    <li>Most expensive option</li>
    <li>Not portable (permanent installation)</li>
    <li>Requires contractor or advanced woodworking skills</li>
</ul>
<p><strong>Best For:</strong> Homeowners with large collections planning long-term display solutions.</p>

<h3>Illuminated Acrylic Display Cases</h3>
<p><strong>Price:</strong> $200-400 per case</p>
<p><strong>Capacity:</strong> 20-50 amiibo</p>
<p><strong>Pros:</strong></p>
<ul>
    <li>Built-in LED edge lighting creates dramatic effects</li>
    <li>High-quality acrylic resists yellowing</li>
    <li>Stackable for multi-tier displays</li>
    <li>Lockable options available</li>
</ul>
<p><strong>Cons:</strong></p>
<ul>
    <li>Expensive for capacity offered</li>
    <li>Acrylic can scratch more easily than glass</li>
</ul>
<p><strong>Best For:</strong> Collectors who prioritize lighting and presentation over capacity.</p>

<h2>Organization Strategies</h2>

<h3>By Series</h3>
<p>Group amiibo by their series (Super Smash Bros., The Legend of Zelda, Super Mario, etc.). This creates cohesive visual groupings and makes specific figures easy to locate.</p>

<h3>By Color</h3>
<p>Arrange figures in color gradients (reds to oranges to yellows to greens, etc.). This creates a visually stunning "rainbow effect" perfect for Instagram-worthy displays.</p>

<h3>By Release Date</h3>
<p>Chronicle your collection's growth by displaying in release order, from Wave 1 (2014) to present. This tells the story of amiibo's evolution.</p>

<h3>By Personal Favorites</h3>
<p>Feature your most-loved characters front-and-center, with less important figures in background positions. This personalizes your display and highlights what matters to you.</p>

<h3>NIB vs. OOB Hybrid</h3>
<p>Display NIB amiibo on upper shelves (where boxes are visible) and OOB figures on lower shelves (where you can appreciate sculpts up close). This maximizes both space and visual appeal.</p>

<h2>Protection and Maintenance</h2>

<h3>Dust Prevention</h3>
<ul>
    <li><strong>Enclosed Cases:</strong> Best protection; dust can't reach figures inside glass or acrylic</li>
    <li><strong>Regular Dusting:</strong> For open shelves, dust weekly with microfiber cloths or compressed air</li>
    <li><strong>Air Purifiers:</strong> HEPA air purifiers reduce ambient dust in collector rooms</li>
</ul>

<h3>UV Protection</h3>
<ul>
    <li><strong>Avoid Direct Sunlight:</strong> UV rays fade paint and yellow plastic over months/years</li>
    <li><strong>UV-Blocking Glass:</strong> Upgrade display cases with UV-filtering acrylic or glass</li>
    <li><strong>Window Treatments:</strong> Use blackout curtains or UV-blocking window film in collector rooms</li>
</ul>

<h3>Earthquake/Pet Safety</h3>
<ul>
    <li><strong>Museum Putty:</strong> Adhesive putty secures figures to shelves without damage ($5-10)</li>
    <li><strong>Anchor Tall Furniture:</strong> Strap bookcases and cabinets to walls to prevent tipping</li>
    <li><strong>Enclosed Cases:</strong> Keep cats and dogs from knocking over figures</li>
</ul>

<h2>Lighting Techniques</h2>

<h3>LED Strip Lights</h3>
<p><strong>Cost:</strong> $10-30 for 15-30 feet</p>
<p><strong>Installation:</strong> Peel-and-stick backing, USB or plug-in powered</p>
<p><strong>Effect:</strong> Ambient glow behind/above figures, highlights shelves</p>

<h3>Spotlights/Track Lighting</h3>
<p><strong>Cost:</strong> $50-200 for system</p>
<p><strong>Installation:</strong> Ceiling or wall-mounted, requires electrical work (or plug-in options)</p>
<p><strong>Effect:</strong> Focused beams highlight specific figures or sections</p>

<h3>Puck Lights</h3>
<p><strong>Cost:</strong> $15-40 for pack of 6-12</p>
<p><strong>Installation:</strong> Battery-powered, stick anywhere</p>
<p><strong>Effect:</strong> Individual spotlights for key figures</p>

<h2>Creative Display Ideas</h2>

<h3>Themed Vignettes</h3>
<p>Create mini-scenes with related amiibo: Link fighting Ganondorf with Bokoblins, Mario and Luigi with Bowser, Inkling teams in battle poses.</p>

<h3>Backdrop Integration</h3>
<p>Print or paint backdrops matching each series (Hyrule landscapes for Zelda amiibo, Mushroom Kingdom for Mario, etc.).</p>

<h3>Risers and Elevation</h3>
<p>Use acrylic risers to create depth—larger figures in back, smaller in front, no figure blocked.</p>

<h3>Rotating Featured Display</h3>
<p>Reserve a prominent spot (mantle, desk) for a monthly "featured amiibo" that rotates regularly.</p>

<h2>Conclusion</h2>
<p>The right display solution depends on your budget, space, collection size, and personal aesthetic. Whether you choose a $10 IKEA shelf or a $500 custom cabinet, the goal remains the same: showcase your collection with pride, protect your investment, and create a display that brings joy every time you see it. Start with what you can afford, upgrade incrementally, and remember—the best display is one that reflects your unique passion for amiibo collecting.</p>
""",
    },
    {
        "slug": "amiibo-release-calendar-2026",
        "title": "Amiibo Release Calendar 2026: Every Confirmed and Rumored Figure",
        "date": "2026-02-10",
        "excerpt": "Stay ahead of upcoming amiibo releases with this comprehensive 2026 calendar covering confirmed figures, rumored leaks, and pre-order information.",
        "content": """
<h2>How to Use This Calendar</h2>
<p>The amiibo release schedule changes frequently due to manufacturing delays, regional variations, and Nintendo's notoriously secretive product planning. This calendar reflects information known as of February 10, 2026, sourced from official Nintendo announcements, retailer listings, and credible leaks from industry insiders. Release dates are subject to change—always verify with official sources before making purchasing decisions.</p>

<p><strong>Legend:</strong></p>
<ul>
    <li><strong>Confirmed:</strong> Officially announced by Nintendo with confirmed release windows</li>
    <li><strong>Rumored:</strong> Leaked via retail databases, insider reports, or pattern analysis (not officially confirmed)</li>
    <li><strong>TBA:</strong> Confirmed to exist but lacking specific release date</li>
</ul>

<div style="text-align: center; margin: 2rem 0;">
    <img src="{% static 'images/blog/amiibo-2026-releases.jpg' %}"
         alt="Calendar showing upcoming 2026 amiibo releases"
         style="max-width: 100%; height: auto; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.3);">
    <p style="font-size: 0.9rem; color: rgba(253, 247, 227, 0.7); margin-top: 0.5rem; font-style: italic;">Stay informed about upcoming amiibo releases throughout 2026</p>
</div>

<p style="font-size: 1.15rem; color: var(--saffron); margin: 1.5rem 0;">Check Nintendo's official website and major retailer pages regularly for restocks and announcements of new releases.</p>

<h2>Q1 2026 Releases (January-March)</h2>

<h3>Confirmed Releases</h3>

<p><strong>Princess Peach (Princess Peach: Showtime!)</strong></p>
<ul>
    <li><strong>Release Date:</strong> March 20, 2026</li>
    <li><strong>Price:</strong> $15.99</li>
    <li><strong>Description:</strong> Peach in her theatrical costume from Princess Peach: Showtime!, featuring a flowing dress with spotlight effects sculpted into the base</li>
    <li><strong>Functionality:</strong> Unlocks exclusive costumes and bonus stages in Princess Peach: Showtime!</li>
    <li><strong>Pre-Order Status:</strong> Opens February 20, 2026 at major retailers</li>
</ul>

<p><strong>Splatoon 3: Expansion Pass Idols 3-Pack</strong></p>
<ul>
    <li><strong>Release Date:</strong> March 28, 2026</li>
    <li><strong>Price:</strong> $39.99 (3-pack)</li>
    <li><strong>Description:</strong> Three new idol characters from Splatoon 3's Side Order expansion: DJ Deepsea, Marina 2.0, and Pearl: Side Order variant</li>
    <li><strong>Functionality:</strong> Unlocks special gear, music tracks, and photo mode poses in Splatoon 3</li>
    <li><strong>Pre-Order Status:</strong> Available now (selling fast)</li>
</ul>

<h3>Rumored Q1 Releases</h3>

<p><strong>Mario Kart 9 Wave 1 (Rumored for Late March)</strong></p>
<ul>
    <li><strong>Expected Characters:</strong> Mario (racing suit), Luigi (racing suit), Peach (racing suit), Bowser (racing suit)</li>
    <li><strong>Source:</strong> Best Buy internal database listings spotted in January 2026</li>
    <li><strong>Likelihood:</strong> High (matches typical Mario Kart launch patterns)</li>
    <li><strong>Expected Price:</strong> $15.99 each</li>
</ul>

<h2>Q2 2026 Releases (April-June)</h2>

<h3>Confirmed Releases</h3>

<p><strong>Metroid Prime 4: Samus (Prime 4 Suit)</strong></p>
<ul>
    <li><strong>Release Date:</strong> May 9, 2026 (launches with Metroid Prime 4)</li>
    <li><strong>Price:</strong> $15.99</li>
    <li><strong>Description:</strong> Samus in her brand-new Prime 4 power suit design, featuring enhanced detail and LED-compatible base (LED not included)</li>
    <li><strong>Functionality:</strong> Unlocks extra difficulty modes and concept art gallery in Metroid Prime 4</li>
    <li><strong>Pre-Order Status:</strong> Opens April 1, 2026</li>
</ul>

<p><strong>Metroid Prime 4: Dark Samus</strong></p>
<ul>
    <li><strong>Release Date:</strong> May 9, 2026</li>
    <li><strong>Price:</strong> $15.99</li>
    <li><strong>Description:</strong> Dark Samus variant with translucent blue plastic and Phazon effects</li>
    <li><strong>Functionality:</strong> Unlocks fusion mode and special weapon skins in Metroid Prime 4</li>
    <li><strong>Pre-Order Status:</strong> Opens April 1, 2026</li>
</ul>

<p><strong>Fire Emblem: Three Houses Anniversary Restock</strong></p>
<ul>
    <li><strong>Release Date:</strong> June 2026 (exact date TBA)</li>
    <li><strong>Characters:</strong> Byleth (Male), Byleth (Female), Edelgard, Dimitri, Claude</li>
    <li><strong>Note:</strong> Not new releases—restocks of 2019-2020 figures to celebrate Three Houses' 7th anniversary</li>
    <li><strong>Expected Availability:</strong> Limited quantities at GameStop, Best Buy, Amazon</li>
</ul>

<h3>Rumored Q2 Releases</h3>

<p><strong>Animal Crossing Series 6 Amiibo Cards (Rumored)</strong></p>
<ul>
    <li><strong>Expected Release:</strong> June 2026</li>
    <li><strong>Expected Contents:</strong> 50-100 cards featuring villagers added in New Horizons updates (2020-2024)</li>
    <li><strong>Source:</strong> Japanese retail listings spotted February 2026</li>
    <li><strong>Likelihood:</strong> Moderate (no official confirmation, but precedent exists)</li>
</ul>

<p><strong>Zelda: Tears of the Kingdom Anniversary Restock</strong></p>
<ul>
    <li><strong>Expected Release:</strong> May 2026 (TOTK 3-year anniversary)</li>
    <li><strong>Expected Figures:</strong> Link (TOTK), Zelda (TOTK), Ganondorf (TOTK)</li>
    <li><strong>Likelihood:</strong> High (anniversary restocks are common)</li>
</ul>

<h2>Q3 2026 Releases (July-September)</h2>

<h3>Confirmed Releases</h3>

<p><strong>Super Smash Bros. Ultimate: Fighters Pass Vol. 3 Wave 1</strong></p>
<ul>
    <li><strong>Release Date:</strong> September 2026 (exact date TBA)</li>
    <li><strong>Expected Characters:</strong> Waluigi, Geno, and two unannounced fighters from the rumored third Fighters Pass</li>
    <li><strong>Note:</strong> Contingent on Nintendo officially announcing Fighters Pass Vol. 3 (unconfirmed as of February 2026)</li>
    <li><strong>Price:</strong> $15.99 each</li>
</ul>

<h3>Rumored Q3 Releases</h3>

<p><strong>Kirby and the Forgotten Land Restock</strong></p>
<ul>
    <li><strong>Expected Release:</strong> August 2026</li>
    <li><strong>Expected Figures:</strong> Kirby (Forgotten Land), Waddle Dee, Elfilin</li>
    <li><strong>Source:</strong> Consistent Q3 Kirby restocks in previous years</li>
    <li><strong>Likelihood:</strong> Moderate</li>
</ul>

<p><strong>Pokémon Legends: Z-A Launch Amiibo (Highly Rumored)</strong></p>
<ul>
    <li><strong>Expected Release:</strong> September 2026 (rumored game launch window)</li>
    <li><strong>Expected Characters:</strong> Zygarde (multiple forms), new starter Pokémon, Legendary mascot</li>
    <li><strong>Source:</strong> Pattern analysis (mainline Pokémon games typically get amiibo)</li>
    <li><strong>Likelihood:</strong> Moderate to High</li>
</ul>

<h2>Q4 2026 & Beyond (October-December+)</h2>

<h3>Confirmed Releases</h3>

<p><strong>Holiday Restocks (Annual Tradition)</strong></p>
<ul>
    <li><strong>Expected Timeframe:</strong> November-December 2026</li>
    <li><strong>Expected Figures:</strong> Popular characters restocked for holiday shopping season (Mario, Link, Pikachu, Kirby, Isabelle, Inkling)</li>
    <li><strong>Note:</strong> Nintendo historically restocks high-demand figures during Q4; specific figures vary by region</li>
</ul>

<h3>Rumored Q4 Releases</h3>

<p><strong>Mario Kart 9 Wave 2 (Rumored for Holiday 2026)</strong></p>
<ul>
    <li><strong>Expected Characters:</strong> Toad, Yoshi, Donkey Kong, Rosalina (all in racing suits)</li>
    <li><strong>Source:</strong> If Wave 1 releases in Q1, Wave 2 typically follows 6-9 months later</li>
    <li><strong>Likelihood:</strong> Moderate</li>
</ul>

<p><strong>Switch 2 Launch Amiibo (Speculative)</strong></p>
<ul>
    <li><strong>Expected Release:</strong> Q4 2026 or Q1 2027 (if Switch 2 launches in this window)</li>
    <li><strong>Expected Characters:</strong> Likely tied to flagship launch titles (3D Mario, Mario Kart 9, or new IP)</li>
    <li><strong>Source:</strong> Precedent from Switch 1 launch (Breath of the Wild amiibo launched with console)</li>
    <li><strong>Likelihood:</strong> Dependent on Switch 2 announcement timing</li>
</ul>

<p><strong>Sanrio Collaboration Cards Re-Restock (Wishful Thinking)</strong></p>
<ul>
    <li><strong>Expected Release:</strong> December 2026 (holiday season)</li>
    <li><strong>Source:</strong> Community wishlist and precedent (restocked March 2021)</li>
    <li><strong>Likelihood:</strong> Low to Moderate (high demand but uncertain Nintendo plans)</li>
</ul>

<h2>Regional Exclusive Watch</h2>
<p>Certain amiibo may release as regional exclusives, requiring imports or secondary market purchases:</p>

<h3>Historical Patterns</h3>
<ul>
    <li><strong>Japan Exclusives:</strong> Historically includes Monster Hunter amiibo, some Splatoon variants, and niche characters (Qbby)</li>
    <li><strong>Europe Exclusives:</strong> Wedding Mario set (2017) never officially released in North America</li>
    <li><strong>Retailer Exclusives (North America):</strong> Best Buy (Gold Mega Man), Target (Shovel Knight), GameStop (Metroid two-packs)</li>
</ul>

<h3>2026 Predictions</h3>
<p>Based on patterns, watch for:</p>
<ul>
    <li>Specialty amiibo from niche franchises (Xenoblade, Fire Emblem) potentially Japan-exclusive</li>
    <li>Holiday bundles (3-packs, special editions) as retailer exclusives in North America</li>
</ul>

<h2>Pre-Order Strategies</h2>

<h3>Where to Pre-Order</h3>
<ul>
    <li><strong>Amazon:</strong> Often opens pre-orders late at night (12-3 AM EST); set up alerts</li>
    <li><strong>Best Buy:</strong> Typically opens pre-orders early morning (9-11 AM EST); in-store pre-orders sometimes available before online</li>
    <li><strong>GameStop:</strong> Pre-orders often open during business hours; in-store typically more stock than online</li>
    <li><strong>Target:</strong> Sporadic pre-order openings; check mornings and late nights</li>
    <li><strong>Nintendo Store:</strong> Official but limited stock; pre-orders sell out fastest here</li>
</ul>

<h3>Maximizing Success</h3>
<ul>
    <li><strong>Multiple Retailers:</strong> Pre-order from 2-3 retailers, cancel duplicates after securing at least one</li>
    <li><strong>Check Regularly:</strong> Visit retailer websites daily during pre-order windows (Best Buy, GameStop, Target, Amazon)</li>
    <li><strong>In-Store:</strong> Physical stores often have separate stock from online; call ahead to check availability</li>
    <li><strong>Payment Ready:</strong> Save payment info to all retailer accounts for one-click checkout</li>
</ul>

<h2>How to Stay Updated</h2>

<h3>Official Sources</h3>
<ul>
    <li><strong>Nintendo Direct:</strong> Major announcements happen during Nintendo Direct presentations (typically quarterly)</li>
    <li><strong>Nintendo's Official Website:</strong> nintendo.com features news about upcoming releases</li>
    <li><strong>Nintendo Store:</strong> store.nintendo.com lists available amiibo and pre-orders</li>
</ul>

<h3>Community Resources</h3>
<ul>
    <li><strong>r/amiibo (Reddit):</strong> Real-time discussions, leak analysis, and community-shared restock information</li>
    <li><strong>Online Collector Forums:</strong> Many amiibo collecting communities share release information and restocks</li>
    <li><strong>YouTube Channels:</strong> Nintendo news channels often cover upcoming amiibo releases</li>
</ul>

<h3>Retailer Emails</h3>
<p>Sign up for email notifications from Best Buy, GameStop, Target, and Amazon for "Amiibo" or "Nintendo collectibles" to receive pre-order announcements.</p>

<h2>2026 Trends and Predictions</h2>

<h3>What to Expect</h3>
<ul>
    <li><strong>Continued Smash Bros. Support:</strong> Even though Ultimate concluded DLC, restocks and potential "Deluxe" or Switch 2 versions may drive new amiibo</li>
    <li><strong>Switch 2 Launch Titles:</strong> Expect 4-8 new amiibo tied to major Switch 2 launch games</li>
    <li><strong>Restock Focus:</strong> Nintendo increasingly prioritizes restocks over new releases to meet demand for existing figures</li>
    <li><strong>Card Series Expansion:</strong> Animal Crossing proved cards are cost-effective; expect more card series for other franchises</li>
</ul>

<h3>Supply Chain Considerations</h3>
<p>Global manufacturing and shipping remain unpredictable. Delays of 4-8 weeks from announced dates are common. Build flexibility into your expectations and budgets.</p>

<h2>Conclusion</h2>
<p>The 2026 amiibo calendar promises exciting releases spanning flagship franchises like Metroid Prime 4, potential Switch 2 launch titles, and beloved restocks. While exact dates remain fluid, staying informed through official channels and community resources ensures you won't miss your must-have figures. Whether you're a completionist tracking every release or a casual collector seeking specific characters, this calendar provides the roadmap for a successful 2026 collecting year.</p>

<p style="font-size: 1.15rem; color: var(--saffron); margin: 1.5rem 0;">Bookmark this guide and check back regularly as Nintendo announces new releases throughout the year!</p>
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
            # Determine appropriate status code based on error type
            if isinstance(error, RateLimitError):
                status_code = 429
            elif isinstance(error, InvalidCredentialsError):
                status_code = 401
            else:
                status_code = 503

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
            # Determine appropriate status code based on error type
            if isinstance(error, RateLimitError):
                status_code = 429
            elif isinstance(error, InvalidCredentialsError):
                status_code = 401
            else:
                status_code = 503

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
            # Determine appropriate status code based on error type
            if isinstance(error, RateLimitError):
                status_code = 429
            elif isinstance(error, InvalidCredentialsError):
                status_code = 401
            else:
                status_code = 503

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
            # Determine appropriate status code based on error type
            if isinstance(error, RateLimitError):
                status_code = 429
            elif isinstance(error, InvalidCredentialsError):
                status_code = 401
            else:
                status_code = 503

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

        # Build SEO context
        seo = SEOContext(request)
        seo.set_title("Welcome to Amiibo Tracker", suffix="")
        seo.set_description(
            "Your one-stop shop for everything Amiibo. Track your collection with Google Sheets, learn about NFC technology, and explore Amiibo history."
        )
        seo.set_type("website")

        # Add WebSite schema with SearchAction
        seo.add_schema("WebSite", generate_website_schema())

        # Add Organization schema
        seo.add_schema("Organization", generate_organization_schema())

        return render(request, "tracker/index.html", seo.build())


class DemoView(View):
    def get(self, request):
        # Build SEO context
        seo = SEOContext(request)
        seo.set_title("Demo", suffix="Amiibo Tracker")
        seo.set_description(
            "Try the Amiibo Tracker demo. See how you can track your collection with Google Sheets integration, filter by series, and manage your Amiibo library."
        )
        seo.set_type("website")

        return render(request, "tracker/demo.html", seo.build())


class PrivacyPolicyView(View):
    def get(self, request):
        # Build SEO context
        seo = SEOContext(request)
        seo.set_title("Privacy Policy", suffix="Amiibo Tracker")
        seo.set_description(
            "Learn how Amiibo Tracker handles your data. We use Google authentication and Sheets for collection tracking. Your data stays in your Google Drive."
        )
        seo.set_type("website")

        context = {
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
        }
        context.update(seo.build())

        return render(request, "tracker/privacy.html", context)


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
        # Load blog posts from JSON file
        posts = load_blog_posts()
        # Sort by date (newest first)
        posts = sorted(posts, key=lambda p: p.get("date", ""), reverse=True)

        self.log_action(
            "blog-list-view",
            request,
            total_posts=len(posts),
        )

        # Build SEO context
        seo = SEOContext(request)
        seo.set_title("Amiibo Blog", suffix="Amiibo Tracker")
        seo.set_description(
            "Learn about Amiibo technology, collecting tips, compatibility guides, and browse the complete catalog of all released Amiibo figures."
        )
        seo.set_type("website")

        # Add Organization schema
        seo.add_schema("Organization", generate_organization_schema())

        context = {"posts": posts}
        context.update(seo.build())

        return render(request, "tracker/blog_list.html", context)


class BlogPostView(View, LoggingMixin, AmiiboRemoteFetchMixin):
    def get(self, request, slug):
        # Load blog posts from JSON and find by slug
        posts = load_blog_posts()
        post = next((p for p in posts if p.get("slug") == slug), None)

        if not post:
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
            title=post.get("title"),
        )

        # Build SEO context
        seo = SEOContext(request)
        seo.set_title(post.get("title"), suffix="Amiibo Blog")

        # Check if content is dynamic
        is_dynamic = post.get("content") == "dynamic"

        # Generate description from excerpt or content
        description = post.get("excerpt") or generate_meta_description(
            post.get("content")
            if not is_dynamic
            else "Browse the complete catalog of all released Amiibo figures, sorted by newest to oldest."
        )
        seo.set_description(description)
        seo.set_type("article")

        # Set OG image if featured_image exists
        if post.get("featured_image"):
            from django.templatetags.static import static

            image_url = static(post["featured_image"])
            seo.set_og_image(image_url)

        # Add Article schema
        post_url = request.build_absolute_uri()
        seo.add_schema(
            "Article",
            generate_article_schema(
                title=post.get("title"),
                description=description,
                url=post_url,
                date_published=post.get("date"),  # Already in ISO format (YYYY-MM-DD)
                author="Amiibo Tracker Team",
                publisher="Amiibo Tracker",
            ),
        )

        # Add BreadcrumbList schema
        breadcrumbs = [
            ("Home", request.build_absolute_uri("/")),
            ("Blog", request.build_absolute_uri("/blog/")),
            (post.get("title"), post_url),
        ]
        seo.add_schema("BreadcrumbList", generate_breadcrumb_schema(breadcrumbs))

        context = {"post": post}
        context.update(seo.build())

        # Handle dynamic content for posts with content="dynamic"
        if is_dynamic:
            try:
                amiibos = self._fetch_remote_amiibos()

                # Add formatted release date and amiibo_id for each amiibo
                for amiibo in amiibos:
                    amiibo["display_release"] = AmiiboService._format_release_date(
                        amiibo.get("release")
                    )
                    # Create amiibo_id in head-tail format for URL
                    amiibo["amiibo_id"] = (
                        f"{amiibo.get('head', '')}-{amiibo.get('tail', '')}"
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

                # Implement pagination (50 items per page)
                page = request.GET.get("page", 1)
                paginator = Paginator(sorted_amiibos, 50)

                try:
                    amiibos_page = paginator.page(page)
                except PageNotAnInteger:
                    amiibos_page = paginator.page(1)
                except EmptyPage:
                    amiibos_page = paginator.page(paginator.num_pages)

                context["amiibos"] = amiibos_page
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


class AmiibodexView(View, LoggingMixin, AmiiboRemoteFetchMixin):
    """View for the Amiibodex page - a comprehensive list of all released amiibo."""

    def get(self, request):
        self.log_action(
            "amiibodex-view",
            request,
        )

        # Build SEO context
        seo = SEOContext(request)
        seo.set_title("Amiibodex", suffix="Complete Amiibo Database")

        description = "Browse the complete catalog of all released Amiibo figures, sorted by newest to oldest. A comprehensive, always up-to-date database of every amiibo ever released."
        seo.set_description(description)
        seo.set_type("website")

        # Add BreadcrumbList schema
        amiibodex_url = request.build_absolute_uri()
        breadcrumbs = [
            ("Home", request.build_absolute_uri("/")),
            ("Amiibodex", amiibodex_url),
        ]
        seo.add_schema("BreadcrumbList", generate_breadcrumb_schema(breadcrumbs))

        context = {}
        context.update(seo.build())

        try:
            amiibos = self._fetch_remote_amiibos()

            # Add formatted release date and amiibo_id for each amiibo
            for amiibo in amiibos:
                amiibo["display_release"] = AmiiboService._format_release_date(
                    amiibo.get("release")
                )
                # Create amiibo_id in head-tail format for URL
                amiibo["amiibo_id"] = (
                    f"{amiibo.get('head', '')}-{amiibo.get('tail', '')}"
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

            # Implement pagination (50 items per page)
            page = request.GET.get("page", 1)
            paginator = Paginator(sorted_amiibos, 50)

            try:
                amiibos_page = paginator.page(page)
            except PageNotAnInteger:
                amiibos_page = paginator.page(1)
            except EmptyPage:
                amiibos_page = paginator.page(paginator.num_pages)

            context["amiibos"] = amiibos_page
            context["total_count"] = len(sorted_amiibos)

            self.log_action(
                "amiibodex-content-loaded",
                request,
                amiibo_count=len(sorted_amiibos),
            )
        except Exception as e:
            self.log_action(
                "amiibodex-content-error",
                request,
                level="error",
                error=str(e),
            )
            context["amiibos"] = []
            context["total_count"] = 0
            context["error"] = True

        return render(request, "tracker/amiibodex.html", context)


class AmiiboDetailView(View, LoggingMixin, AmiiboRemoteFetchMixin):
    """
    View for displaying individual amiibo details.
    URL pattern: /blog/number-released/amiibo/<head>-<tail>/
    """

    def get(self, request, amiibo_id):
        # Parse amiibo_id (format: head-tail)
        try:
            head, tail = amiibo_id.split("-")
            if len(head) != 8 or len(tail) != 8:
                raise ValueError("Invalid amiibo ID format")
        except (ValueError, AttributeError):
            self.log_action(
                "amiibo-detail-invalid-id",
                request,
                level="warning",
                amiibo_id=amiibo_id,
            )
            raise Http404("Invalid amiibo ID")

        # Fetch all amiibos and find the matching one
        try:
            amiibos = self._fetch_remote_amiibos()
            amiibo = next(
                (a for a in amiibos if a.get("head") == head and a.get("tail") == tail),
                None,
            )

            if not amiibo:
                self.log_action(
                    "amiibo-detail-not-found",
                    request,
                    level="warning",
                    amiibo_id=amiibo_id,
                )
                raise Http404("Amiibo not found")

            # Add formatted release dates
            amiibo["display_release"] = AmiiboService._format_release_date(
                amiibo.get("release")
            )

            # Format regional release dates
            release_dates = amiibo.get("release", {})
            regional_releases = []
            region_names = {
                "na": "North America",
                "jp": "Japan",
                "eu": "Europe",
                "au": "Australia",
            }

            for region_code, region_name in region_names.items():
                date_str = release_dates.get(region_code)
                if date_str:
                    try:
                        from datetime import datetime

                        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                        formatted_date = date_obj.strftime("%B %d, %Y")
                        regional_releases.append(
                            {"region": region_name, "date": formatted_date}
                        )
                    except (ValueError, TypeError):
                        pass

            # Get character description
            description = self._get_character_description(amiibo)
            self.log_info(
                f"Description loaded for {amiibo.get('name')}: {description[:100]}..."
                if len(description) > 100
                else f"Description loaded for {amiibo.get('name')}: {description}"
            )

            # Build SEO context
            seo = SEOContext(request)
            amiibo_name = amiibo.get("name", "Unknown Amiibo")
            seo.set_title(f"{amiibo_name} Details", suffix="Amiibo Tracker")

            # Generate description from amiibo data
            game_series = amiibo.get("gameSeries", "")
            amiibo_series = amiibo.get("amiiboSeries", "")
            release_info = amiibo.get("display_release", "")
            meta_description = f"{amiibo_name} amiibo from {game_series}. Part of the {amiibo_series} series."
            if release_info:
                meta_description += f" Released {release_info}."
            seo.set_description(meta_description[:155])

            seo.set_type("product")

            # Set OG image if available
            if amiibo.get("image"):
                seo.set_og_image(amiibo["image"])

            # Add Product schema
            product_url = request.build_absolute_uri()
            earliest_release = None
            for region in ["na", "jp", "eu", "au"]:
                date_str = release_dates.get(region)
                if date_str:
                    earliest_release = date_str
                    break

            seo.add_schema(
                "Product",
                generate_product_schema(
                    name=amiibo_name,
                    description=description or meta_description,
                    image=amiibo.get("image", ""),
                    url=product_url,
                    release_date=earliest_release,
                    brand="Nintendo",
                ),
            )

            # Add BreadcrumbList schema
            breadcrumbs = [
                ("Home", request.build_absolute_uri("/")),
                ("Blog", request.build_absolute_uri("/blog/")),
                ("All Amiibo", request.build_absolute_uri("/blog/number-released/")),
                (amiibo_name, product_url),
            ]
            seo.add_schema("BreadcrumbList", generate_breadcrumb_schema(breadcrumbs))

            context = {
                "amiibo": amiibo,
                "regional_releases": regional_releases,
                "description": description,
            }
            context.update(seo.build())

            # Log context description to verify it's correct
            self.log_info(
                f"Context description for template: {context['description'][:100]}..."
                if len(context["description"]) > 100
                else f"Context description for template: {context['description']}"
            )

            self.log_action(
                "amiibo-detail-view",
                request,
                amiibo_id=amiibo_id,
                amiibo_name=amiibo.get("name"),
            )

            return render(request, "tracker/amiibo_detail.html", context)

        except Exception as e:
            self.log_action(
                "amiibo-detail-error",
                request,
                level="error",
                amiibo_id=amiibo_id,
                error=str(e),
            )
            raise

    def _get_character_description(self, amiibo):
        """
        Get character description. First tries to load from JSON file using amiibo name,
        then falls back to character name, then template-based description.
        """
        amiibo_name = amiibo.get("name", "")
        character_name = amiibo.get("character", "")
        game_series = amiibo.get("gameSeries", "")

        # Try to load custom descriptions from JSON file
        descriptions_path = (
            Path(__file__).parent / "data" / "character_descriptions.json"
        )
        if descriptions_path.exists():
            try:
                with open(descriptions_path, "r", encoding="utf-8") as f:
                    descriptions = json.load(f)
                    # Try amiibo name first (for variant-specific descriptions)
                    if amiibo_name in descriptions:
                        self.log_info(
                            f"Found description for amiibo name: {amiibo_name}"
                        )
                        return descriptions[amiibo_name]
                    # Fall back to character name
                    if character_name in descriptions:
                        self.log_info(
                            f"Found description for character name: {character_name}"
                        )
                        return descriptions[character_name]
                    # Log when no match is found
                    self.log_info(
                        f"No description found for amiibo_name='{amiibo_name}' or character_name='{character_name}'"
                    )
            except Exception as e:
                self.log_warning(
                    f"Error loading character descriptions: {e}. Falling back to template description."
                )

        # Template-based description (fallback)
        if character_name and game_series:
            return f"{character_name} is a character from the {game_series} series."
        elif character_name:
            return f"{character_name} is featured in this amiibo."
        else:
            return "This amiibo features a character from Nintendo's gaming universe."


class RobotsTxtView(View):
    """
    Serves the robots.txt file with proper content type.
    """

    def get(self, request):
        robots_path = Path(__file__).parent.parent / "static" / "robots.txt"
        try:
            with open(robots_path, "r", encoding="utf-8") as f:
                content = f.read()
            return HttpResponse(content, content_type="text/plain")
        except FileNotFoundError:
            return HttpResponse("User-agent: *\nAllow: /\n", content_type="text/plain")
