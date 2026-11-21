"""Orthogonal, non-bleeding dropdown presets and prompt assembly helpers for Graphical Studio."""

import re

import addons

THEME_FIELDS = [
    ("rating", "Rating / Content", "rating", [
        "None / Standard",
        "Safe / Clean (SFW): rating_safe, clean family-friendly tone",
    ]),
    ("style", "Visual Style", "style", [
        "None / Custom",
        # Photoreal cluster
        "American Realistic Photo: RAW candid photo, photorealistic modern American lifestyle photography, Sony A7R V 35mm f/1.8 lens",
        "Cinematic Film Still: live-action 35mm cinema still, anamorphic depth of field, filmic color grading",
        "Editorial Magazine Portrait: high-fashion editorial photography, 85mm f/1.4 shallow bokeh, refined detail",
        "35mm Analog Film (Kodak Portra): nostalgic 35mm analog film photograph, organic fine grain, soft filmic tones",
        "90s Instant Polaroid: vintage instant-film photograph, subtle retro color cast, soft analog vignette",
        "Casual Smartphone Vlog: authentic smartphone front-camera video frame, slight sensor grain, natural exposure",
        "Creator 4K Webcam: crisp 4K digital creator camera aesthetic, sharp clean focus, modern color science",
        "Dark Neo-Noir Cinema: atmospheric neo-noir visual style, high-contrast shadow grading, moody desaturated palette",
        # Illustrated / Anime / Comic
        "2.5D Semi-Realistic: semi-realistic detailed digital illustration, soft volumetric shading, rich brushwork",
        "Anime Visual Novel: high-detail Japanese anime visual novel illustration, crisp ink linework, layered cel shading",
        "Modern JRPG Illustration: vibrant modern JRPG character art style, stylized clean shading, polished lineart",
        "Western Graphic Novel / Comic: bold comic-book ink outlines, graphic halftone shading, punchy color palette",
        # Dark minimal wallpaper looks (monochrome + spot color; white-on-black lineart)
        "Dark Monochrome Anime: dark moody anime illustration, high contrast, soft cel shading, deep shadows",
        "Inverted Lineart (White on Black): white anime lineart on a pure black background, inverted colors, monochrome sketch lines, flat white fill, no shading",
        # Painted
        "Hand-Painted Fantasy Concept: painterly fantasy RPG concept art, visible expressive brushstrokes, rich texture",
        "Classical Oil Painting: classical fine-art oil painting brushwork, rich canvas texture, traditional glazing",
        # Digital / 3D / Pixel
        "Unreal Engine 5 / 3D Render: next-gen 3D game engine render, physically based PBR materials, global illumination",
        "Cyberpunk Synthwave Art: futuristic cyberpunk visual aesthetic, chromatic edge accents, stylized neon palette",
        "Retro 16-Bit Pixel Art: crisp 16-bit indie game pixel art, clean pixel cluster shading, limited palette",
    ]),
    ("color_treatment", "Color Treatment", "color_treatment", [
        "None / Custom",
        "Full Vibrant Color: vibrant saturated colors",
        "Muted / Desaturated: muted desaturated colors, low saturation",
        "Monochrome Greyscale: monochrome, greyscale",
        "High-Contrast Black & White: black and white, high contrast, deep blacks, bright highlights",
        "Sepia Tone: sepia, warm brown monochrome tones",
        "Duotone: duotone, two-color palette",
        "Limited Palette: limited palette, three-color scheme",
        "Spot Color (Greyscale + Kept Color): monochrome, greyscale, spot color",
    ]),
    ("spot_color", "Color Kept On (Spot Color)", "spot_color", [
        "None / Custom",
        "Eyes: colored eyes, only the eyes in vivid color",
        "Eyes & Lips: only the eyes and lips in color",
        "Lips: only the lips in color, red lips",
        "Hair: only the hair in color, colored hair",
        "Clothing / Outfit: only the clothing in color",
        "Accessories / Jewelry: only the jewelry and accessories in color",
        "Flowers / Props: only the flowers and props in color",
        "Background Accent: only a background accent in color",
    ]),
    ("lighting", "Mood & Lighting", "lighting", [
        "None / Custom",
        # Natural daylight
        "Bright Morning Daylight: crisp cheerful natural daylight, clean airy exposure, neutral white balance",
        "Dappled Filtered Sunlight: warm broken natural light beams with gentle dappled shadow patterns",
        "Golden Hour Sunlight: warm golden late-afternoon directional sunlight with soft long shadows",
        "Blue Hour Twilight: cool evening blue-hour ambient light balanced by warm practical highlights",
        # Night / dark
        "Neon Rainy Night: cool dark teal night shadows pierced by vibrant magenta and amber neon reflections",
        "Cool Silver Moonlight: pale silvery nighttime moonlight with soft cool shadows",
        "Mixed Fluorescent Night Glow: stylized cool overhead fluorescent mixed with warm practical light",
        # Indoor warm
        "Dim Romantic Candlelight: low-key warm amber flickering glow with deep cozy shadows",
        "Warm Hearth Ember Glow: warm flickering orange-amber low-angle firelight glow",
        # Indoor studio
        "Soft Front Ring-Light + Warm Fill: balanced front ring-light key with soft warm ambient fill",
        "Diffused Studio Softbox: clean flattering overcast softbox lighting, even balanced highlights",
        "Direct On-Camera Flash: punchy direct flash exposure, crisp frontal highlights, fast background falloff",
        "RGB Neon Accent Backlight: clean neutral key light with soft magenta and cyan colored rim backlight",
        # Dramatic
        "Dramatic Chiaroscuro Rim: high-contrast low-key side lighting with sharp luminous rim separation",
        "Low-Key Spotlight Fade: low-key lighting, soft overhead spotlight on the figure, body fading into darkness, subtle rim light",
        "Vibrant Stage Beams: colorful directional beam lighting cutting through light atmospheric haze",
    ]),
    ("framing", "Camera Framing", "framing", [
        "None / Custom",
        # Wide to tight
        "Wide Environmental Framing: wide-angle framing placing subject within a broad view of the setting",
        "Full Body (Head-to-Toe, Anti-Zoom): full body, head-to-toe wide framing showing full figure",
        "Three-Quarter (Knees-Up, Anti-Zoom): three-quarter knees-up framing showing silhouette and proportions",
        "Cowboy Shot (Thighs-Up, Anti-Zoom): cowboy shot, thighs-up framing, wide enough to show torso and hips",
        "Upper Body (Waist-Up, Anti-Zoom): upper body, waist-up medium shot centered on subject",
        "Medium Close-Up (Chest-Up): medium close-up chest-up eye-level framing, shallow background blur",
        "Extreme Close-Up Face: tight intimate close-up framing face and collarbones, creamy background bokeh",
        # Special angles
        "High-Angle Perspective: slightly elevated high camera angle tilted gently downward",
        "Low-Angle Power Perspective: low camera angle tilted slightly upward for bold presence",
        "Over-the-Shoulder POV: first-person over-the-shoulder camera perspective",
        "Side Profile Framing: clean side-profile or three-quarter turn camera framing",
        "Dutch Tilt Dynamic Angle: subtle diagonal Dutch-angle camera tilt for visual tension",
        "Overhead Top-Down Angle: elevated bird's-eye overhead camera perspective",
    ]),
    ("composition", "Subject Position", "composition", [
        "None / Custom",
        "Far Left: character at the far left edge of the frame, large empty space on the right",
        "Left Third: character on the left third of the frame, empty space on the right, rule of thirds",
        "Centered: character centered in the frame, balanced symmetrical composition",
        "Right Third: character on the right third of the frame, empty space on the left, rule of thirds",
        "Far Right: character at the far right edge of the frame, large empty space on the left",
        "Cropped at Frame Edge: figure partly cropped by the frame edge, off-center close crop",
        "Small Figure, Vast Space: small figure in a vast empty frame, minimalist composition",
    ]),
]

PERSON_FIELDS = [
    ("gender", "Subject / Gender", "gender", [
        "None / Custom",
        # Solo
        "Solo Woman: 1woman, adult female subject, centered",
        "Solo Man: 1man, adult male subject, centered",
        # Duo / Couple
        "Romantic Couple: 1man and 1woman together, balanced two-shot",
        "Two Women Together: 2women together, balanced two-shot",
        "Two Men Together: 2men together, balanced two-shot",
        "Two Friends Together: two young adults together, candid interaction",
        # Group
        "Small Group: small group of people in natural candid grouping",
        # Fantasy / Sci-Fi
        "Fantasy Adventurer Woman: 1woman, adult female fantasy character",
        "Fantasy Adventurer Man: 1man, adult male fantasy character",
        "Sci-Fi Mercenary: solo adult futuristic mercenary character",
        # Empty
        "Empty Environment (No People): no humans, empty scenery without people",
    ]),
    ("symmetry", "Facial Structure", "symmetry", [
        "None / Custom",
        # Soft / delicate
        "Soft Oval Delicate: gentle oval face contour, delicate nose, soft balanced proportions",
        "Heart-Shaped Youthful: delicate heart-shaped face, softly contoured cheeks, tapered chin",
        "Everyday Natural Pretty: pleasant approachable balanced facial features, natural everyday appeal",
        # Harmonious / high symmetry
        "High Symmetry (Classic): very attractive, harmonious symmetrical face, sculpted cheekbones, balanced proportions",
        "Top Model Sculpted: striking photogenic facial symmetry, defined jawline, high cheekbones",
        # Striking / editorial
        "Angular High-Fashion: sharp editorial cheekbones, narrow defined jawline, striking bone structure",
        # Masculine / strong
        "Strong Chiseled Structure: strong brow line, crisp angular jaw, bold balanced bone structure",
        # Character
        "Weathered Character Face: lived-in charismatic facial features, subtle authentic expression lines",
    ]),
    ("age", "Age & Vibe", "age", [
        "None / Custom",
        "18-21 Young Adult: 20 years old young adult, fresh youthful energy",
        "Early 20s Adult: early 20s adult, energetic modern youthfulness",
        "Mid 20s Adult: mid-20s young adult, confident approachable maturity",
        "Late 20s Adult: late-20s adult, self-assured poised presence",
        "Early 30s Prime: early-30s mature adult, polished confident presence",
        "Mid-to-Late 30s: mid-30s sophisticated adult, refined composure",
        "40s Seasoned Adult: mid-40s charismatic mature adult, seasoned authority",
        "50s+ Distinguished: distinguished older adult, calm silver-age poise",
        "Timeless Ageless: ageless ethereal character presence",
    ]),
    ("build", "General Build", "build", [
        "None / Custom",
        # Slender / lean
        "Petite Lean: petite lean narrow frame, delicate shoulders",
        "Slender Athletic: toned slender athletic physique, balanced proportions",
        "Tall Slender Model: tall long-limbed slender proportions",
        "Lean Endurance Runner: wiry lean endurance physique, defined lines",
        # Athletic / fit
        "Compact Nimble Athletic: compact toned dancer physique, agile frame",
        "Toned Fitness / Core: visibly toned core and shoulders, sculpted lean fitness physique",
        # Curvy
        "Fit Curvy / Hourglass: fit shapely hourglass physique, balanced curves",
        "Voluptuous / Full-Figured: lush curvy full-figured proportions, soft silhouette",
        # Average / heavy
        "Realistic Average Build: natural everyday medium build",
        "Muscular Broad-Shouldered: athletic muscular build, broad shoulders",
        "Heavy Broad Powerlifter: solid powerful broad-chested physique",
    ]),
    ("hair_color", "Hair Color", "hair_color", [
        "None / Custom",
        # Light to dark (natural)
        "Platinum Ice Blonde: luminous icy platinum blonde hair with subtle natural roots",
        "Dirty Blonde / Balayage: dimensional dirty-blonde hair with natural balayage highlights",
        "Golden Honey Blonde: warm golden honey-blonde hair",
        "Strawberry Blonde / Ginger: soft natural strawberry-blonde ginger hair",
        "Warm Caramel Brown: warm caramel brown hair with subtle lighter highlights",
        "Rich Chestnut Brunette: rich chestnut brunette hair",
        "Copper Auburn Red: vibrant copper-auburn red hair",
        "Deep Crimson / Wine Red: rich deep burgundy wine-red hair",
        "Dark Espresso Brown: deep dark espresso brown hair",
        "Jet Raven Black: glossy jet-black raven hair",
        # Fantasy / dyed
        "Silver-White / Ash Grey: luminous silver-white ash hair",
        "Pastel Pink / Rose Gold: soft pastel rose-pink dyed hair with dark roots",
        "Lavender / Soft Violet: pastel lavender-violet dyed hair",
        "Midnight Blue / Teal Tips: dark hair with vivid midnight-blue and teal dyed ends",
        "Two-Tone Split Dye: bold modern two-tone split-dyed hair",
    ]),
    ("hair_style", "Hair Style", "hair_style", [
        "None / Custom",
        # Long
        "Long Flowing Layered: long flowing layered hair cascading past shoulders",
        "Curtain Bangs + Long Layers: curtain bangs framing face with voluminous long layers",
        "Soft Loose Shoulder Waves: falling in loose soft shoulder-length waves",
        "Voluminous Bouncy Curls: rich voluminous bouncy curls framing the face",
        "Beach Tousled Waves: relaxed tousled textured waves",
        # Medium
        "Tousled Medium Waves: relaxed medium-length tousled hair pushed loosely back",
        "Wolf Cut Shaggy Layers: textured shaggy wolf-cut with choppy face-framing layers",
        "Half-Up Half-Down: half-up half-down hairstyle with soft framing tendrils",
        # Updo / pulled back
        "Casual Messy Bun: pulled into a loose effortless messy bun with face-framing strands",
        "High Sleek Ponytail: pulled into a glossy high ponytail swinging cleanly over shoulder",
        "Low Wavy Ponytail: tied in a relaxed low wavy ponytail with soft loose wisps",
        # Short
        "Sleek Straight Tucked Behind Ear: glossy straight hair tucked casually behind one ear",
        "Chin-Length Sleek Bob: chic chin-length bob haircut, crisp modern cut",
        "Pixie Cut Short Textured: short textured pixie cut",
        "Clean Short Textured Cut: clean short textured modern haircut, neatly styled",
        "Modern Fade Undercut: sharp tapered side fade with textured volume on top",
        # Special / braids
        "Twin Braids / Space Buns: twin braided pigtails or twin space buns",
        "Long Box Braids / Natural Coils: neat long box braids or rich textured natural coils",
    ]),
    ("eyes", "Eye Color & Shape", "eyes", [
        "None / Custom",
        # ROYGBIV order: amber/orange → green → blue → violet → brown → special/shape
        "Honey Amber: striking light honey-amber eyes",
        "Hazel (Green-Gold Flecks): expressive hazel eyes with warm golden-green flecks",
        "Emerald Green: vivid emerald green eyes",
        "Crystal Ocean Blue: bright crystal ocean-blue eyes",
        "Ice-Blue / Storm Grey: pale ice-blue grey eyes with sharp iris ring",
        "Teal / Aqua: luminous teal aqua eyes",
        "Crimson Red: vivid crimson red eyes",
        "Blue-Gold Heterochromia: blue eyes with warm golden central heterochromia",
        # Brown tones
        "Warm Chocolate Brown: deep warm chocolate-brown eyes",
        "Dark Espresso Brown: rich dark velvety espresso-brown eyes",
        # Special / shape
        "Glowing Arcane / Cyber Irises: subtly luminous glowing stylized irises",
        "Almond Shaped Eyes: sleek almond-shaped expressive eyes",
        "Large Round Bright Eyes: large bright round expressive eyes",
    ]),
    ("skin", "Skin Tone & Texture", "skin", [
        "None / Custom",
        # Light to dark
        "Fair Porcelain Tone: fair clear porcelain skin tone",
        "Fair with Light Freckles: fair clear skin with faint natural nose and cheek freckles",
        "Warm Sun-Kissed Olive: warm sun-kissed olive complexion",
        "Golden-Bronze Undertone: warm golden-bronze complexion with natural undertones",
        "Warm Caramel Brown: luminous warm caramel-brown skin tone",
        "Rich Deep Warm Complexion: rich luminous deep dark skin tone",
        # Texture variants
        "Natural Realistic Texture: authentic natural skin texture with fine pores and realistic sheen",
        "Post-Workout Dewy Flush: lightly flushed natural skin with subtle dewy sheen",
        "Weathered Gritty Texture: rugged realistic skin texture with subtle faint scars and grit",
        "Smooth Stylized Finish: ultra-smooth clean stylized skin shading with soft blush",
    ]),
    ("makeup_acc", "Makeup & Accessories", "makeup_acc", [
        "None / Custom",
        # Natural / minimal makeup
        "Bare-Faced / Minimal Natural: fresh bare-faced minimal natural makeup",
        "Soft Everyday Dewy Glam: subtle lip gloss, light mascara, soft natural cheek blush",
        # Makeup
        "Winged Eyeliner & Bold Lip: crisp winged cat-eye eyeliner, softly contoured blush, satin lipstick",
        "Smoky Evening Glam: soft smoky eyeshadow, defined brows, luminous cheek highlighter",
        # Eyewear
        "Thin Minimalist Eyeglasses: sleek thin-rimmed modern eyeglasses",
        "Stylish Sunglasses: chic dark-tinted sunglasses",
        # Jewelry
        "Layered Delicate Gold Jewelry: dainty layered gold necklaces and small hoop earrings",
        "Chunky Silver Chains & Rings: layered silver chain necklaces and modern rings",
        # Accessories
        "Over-Ear Studio Headphones: sleek over-ear headphones resting around neck or over ears",
        "Casual Baseball Cap / Beanie: relaxed fitted baseball cap or knit beanie",
        "Subtle Tattoos & Piercings: tasteful fine-line forearm tattoos and subtle ear piercings",
    ]),
]

SCENE_ATTIRE_FIELDS = [
    ("attire", "Attire / Outfit", "attire", [
        "None / Custom",
        # Casual daily
        "Fitted White Tee & Blue Jeans: crisp fitted white crew-neck t-shirt and relaxed blue denim jeans",
        "Oversized Graphic Tee & Cargos: oversized vintage graphic t-shirt paired with relaxed cargo pants or bike shorts",
        "Ribbed Crop Top & Baggy Jeans: fitted cropped ribbed baby-tee showing bare midriff, relaxed low-rise blue denim jeans",
        "Cropped Tank & Open Flannel: fitted cropped ribbed tank top under an unbuttoned plaid flannel shirt",
        "Cropped Cardigan & High-Waist Jeans: buttoned knit cropped cardigan showing hint of midriff, fitted high-waisted blue jeans",
        "Off-Shoulder Crop Top & Mini Skirt: fitted off-the-shoulder knit crop top exposing collarbones and midriff, pleated mini skirt",
        "Cropped Zip Hoodie & Joggers: cropped zip-up athletic hoodie over fitted ribbed tank showing midriff, high-waisted joggers",
        "Oversized Off-Shoulder Sweater: chunky knit oversized sweater slipping off one shoulder with ribbed thigh socks",
        # Athletic
        "Athleisure Crop Tank & Leggings: sleek cropped halter athletic tank top and high-waisted sculpted leggings",
        "Sports Bra & Running Shorts: matching fitted athletic sports bra and short compression running shorts",
        # Outerwear
        "Leather Moto Jacket & Dark Jeans: fitted black leather biker jacket layered over cropped white tee and dark jeans",
        # Dresses
        "Floral Summer Sundress: lightweight breezy floral sundress with delicate tie straps",
        "Satin Evening Slip Dress: sleek satin evening slip dress with delicate spaghetti straps",
        # Professional / formal
        "Tailored Executive Blazer Suit: tailored charcoal blazer over a silk camisole and fitted trousers",
        "Open-Collar Button-Down & Chinos: tailored open-collar Oxford button-down shirt with rolled sleeves and dark chinos",
        # Fantasy / special
        "Fantasy Leather RPG Armor: detailed studded fantasy adventurer leather armor, pauldrons, cloak clasp, belt pouches",
        "Cyberpunk Techwear Jacket: futuristic matte-black techwear shell jacket with neon trim accents and tactical straps",
    ]),
    ("pose", "Body Posture / Pose", "pose", [
        "None / Custom",
        # Standing
        "Standing Relaxed (Hip Shift): standing naturally, weight shifted casually to one hip",
        "Standing Tall Confident: standing upright with poised shoulders and confident stance",
        "Arms Crossed Stance: standing with arms lightly crossed across torso",
        "Leaning Back / Angled Relaxed: leaning back casually with one hand resting near hip",
        "Leaning Forward Slightly: torso angled slightly forward in an engaging open posture",
        # Sitting
        "Seated Upright Relaxed: seated upright with relaxed shoulders and natural posture",
        "Seated Cross-Legged: sitting cross-legged in a comfortable open posture",
        "Seated Lounging Back: seated leaning back comfortably with legs relaxed",
        # Special / dynamic
        "One Hand Brushing Hair: lifting one hand casually to tuck or brush hair behind ear",
        "Looking Back Over Shoulder: body angled away while turning head back over shoulder",
        "Stretching Arms Overhead: raising arms gracefully overhead in a relaxed stretch",
        "Mid-Stride Walking Forward: stepping smoothly forward in a natural mid-stride walk",
        "Dynamic Hip Sway / Dance Pose: lively mid-movement dance posture with expressive shoulders",
        # Reclining / low
        "Reclining / Lying Back: reclining comfortably on back or side with relaxed limbs",
        "Low Crouching / Kneeling: low crouched or kneeling dynamic posture",
    ]),
    ("surface_prop", "Surface / Furniture / Prop", "surface_prop", [
        "None / Custom",
        # Furniture
        "On Bed / Soft Pillows: positioned on an unmade bed with soft rumpled pillows",
        "On Plush Living Room Couch: positioned on a soft modern fabric sofa",
        "In Ergonomic Gaming / Desk Chair: positioned in an ergonomic chair next to a computer desk",
        # Architecture
        "Against Wall / Doorframe: resting shoulder or back lightly against a wall or doorframe",
        "By Floor-to-Ceiling Window / Balcony: positioned beside a tall glass window or balcony railing",
        "At Counter / Kitchen Island: next to a sleek counter or tabletop with forearms resting lightly",
        # Mirrors / tech
        "In Front of Full-Length Mirror: framed in front of a large mirror holding a smartphone",
        "Next to Desk Microphone & Monitors: positioned beside a broadcast boom mic and glowing dual monitors",
        # Handheld
        "Holding Smartphone: holding a modern smartphone naturally in hand",
        "Holding Iced Coffee / Mug: holding a cold iced coffee cup or warm ceramic mug",
        "Holding Fantasy Weapon / Lantern: holding an ornate sword, staff, or glowing lantern",
        # Special
        "In Car Passenger Seat: positioned inside a car passenger seat with seatbelt visible",
        "Open Unobstructed Floor / Ground: standing freely in open space with no foreground furniture",
    ]),
    ("scene", "Scene / Location", "scene", [
        "None / Custom",
        # Interior — residential
        "Modern Bedroom: cozy modern American bedroom with dresser, framed wall art, and soft fabric decor",
        "Modern Apartment Living Room: airy contemporary living room with indoor monstera plants and hardwood floors",
        "Contemporary Kitchen: sleek modern kitchen with marble island, cabinetry, and ceramic tableware",
        # Interior — luxury / work
        "High-Rise Penthouse Interior: 60th-floor luxury high-rise apartment overlooking a sprawling city skyline",
        "Open-Air Rooftop Patio: upscale rooftop terrace with lounge seating and panoramic downtown skyline",
        "Upscale Hotel Suite: refined luxury hotel suite with sheer curtains and balcony doors",
        "Creator / Gaming Studio Room: modern creator room with acoustic wall panels, shelves, and tidy desk setup",
        # Interior — public
        "Boutique Fitness Gym: clean modern fitness studio with wall mirrors, kettlebells, and matte rubber flooring",
        "Artisan Coffee Shop: cozy neighborhood cafe interior with wood counters, espresso bar, and blurred patrons",
        "Retro American Diner: classic vintage diner with red vinyl booths, chrome trim, and tiled floor",
        "Minimalist Photo Studio: clean seamless portrait photography studio backdrop",
        "Green-Screen Backdrop (#00FF00): solid flat bright chroma-key green (#00FF00) studio backdrop, zero clutter",
        # Outdoor
        "Sandy Ocean Coastline: wide sandy beach coastline with gentle turquoise waves and open horizon",
        "Botanical Park Walkway: lush green park trail lined with blooming trees and manicured foliage",
        "Urban Rain-Slicked Alley: atmospheric city street with brick facades, shop signage, and wet asphalt",
        "Modern Car Interior: clean contemporary car cabin looking out toward blurred road scenery",
        # Fantasy / Sci-Fi
        "Medieval Fantasy Tavern: rustic timber-beam fantasy inn with oak barrels, stone hearth, and wooden tables",
        "Ancient Forest Ruins: mossy weathered stone archway surrounded by towering woodland trees",
        "Sci-Fi Starship Bridge: futuristic spacecraft observation deck with holographic consoles and starfield viewport",
    ]),
    ("bg_type", "Background Type", "bg_type", [
        "None / Custom",
        "Solid Color: simple background, plain solid-color background, no scenery",
        "Linear Gradient: gradient background, smooth color gradient, simple background",
        "Radial Glow / Vignette: radial gradient background, soft glow behind the subject, dark vignette edges, simple background",
        "Repeating Gradient Bands: repeating gradient stripes background, banded color gradient",
        "Two-Tone Split: two-tone background, split diagonal background",
        "Paint Splashes: paint splatter background, bold paint splashes and ink drips",
        "Ink Wash / Watercolor: watercolor wash background, soft ink bleed, painterly backdrop",
        "Abstract Shapes: abstract background, floating geometric shapes, graphic design backdrop",
        "Geometric Pattern: geometric pattern background, repeating triangles and lines",
        "Halftone Dots: halftone background, pop-art dot pattern",
        "Polka Dots: polka dot background",
        "Bokeh Lights: bokeh background, blurred circular light orbs",
        "Smoke / Mist: smoky background, drifting mist, atmospheric haze",
        "Starfield / Night Sky: starry sky background, scattered stars",
        "Light Rays / Sunburst: light rays background, radiating sunburst beams",
    ]),
    ("bg_color", "Background Color", "bg_color", [
        "None / Custom",
        "Pure Black: black background",
        "Very Dark Grey (Charcoal): dark grey background, charcoal backdrop",
        "Mid Grey: grey background",
        "White: white background",
        "Warm Cream / Beige: beige background",
        "Deep Navy: dark blue background",
        "Midnight Purple: dark purple background",
        "Crimson Red: red background",
        "Teal: teal background",
        "Emerald Green: green background",
        "Gold / Amber: orange-gold background",
        "Pastel Pink: pink background",
        "Black to Grey Gradient: black and dark grey background",
        "Sunset Orange to Purple: orange and purple background",
    ]),
]

MOTION_FIELDS = list(addons.REGISTRY.video_motion_fields or [])

if addons.REGISTRY.extend_catalog:
    addons.REGISTRY.extend_catalog(THEME_FIELDS, PERSON_FIELDS, SCENE_ATTIRE_FIELDS, MOTION_FIELDS)

ALL_GROUPS = [
    ("1. Theme, Style & Camera", THEME_FIELDS),
    ("2. Person Characteristics", PERSON_FIELDS),
    ("3. Attire, Pose, Props & Location", SCENE_ATTIRE_FIELDS),
    *([("4. Video Motion & Camera Action (For Video Tab)", MOTION_FIELDS)] if MOTION_FIELDS else []),
]
ALL_FIELDS = THEME_FIELDS + PERSON_FIELDS + SCENE_ATTIRE_FIELDS + MOTION_FIELDS
FIELD_BY_KEY = {f[0]: f for f in ALL_FIELDS}
QUICK_PHOTO_KEYS = ("style", "scene", "gender", "symmetry", "attire", "framing")
QUICK_VIDEO_KEYS = ("style", "scene", "gender", "symmetry", "attire", "motion") if MOTION_FIELDS else QUICK_PHOTO_KEYS
MOTION_KEYS = {f[0] for f in MOTION_FIELDS}


def extract_clause(raw_value: str) -> str:
    """Return prompt keywords from a 'Short Label: keywords' combo string or custom user text."""
    clean = (raw_value or "").strip()
    if not clean or clean.lower().startswith("none"):
        return ""
    if ":" in clean:
        head, tail = clean.split(":", 1)
        if len(head) <= 44 and tail.strip():
            return tail.strip()
    return clean


def assemble_builder_prompt(values: dict[str, str], include_motion: bool = True, extra_notes: str = "") -> str:
    """Assemble selected dropdown values into one conflict-rectified comma-separated prompt."""
    from wan_rectifier import rectify_builder_fields

    extras = [("extra_notes", extra_notes.strip())] if (extra_notes or "").strip() else None
    rectified, _ = rectify_builder_fields(values, extra_clauses=extras, include_motion=include_motion)
    return rectified


def assemble_motion_only(values: dict[str, str], extra_notes: str = "") -> str:
    """Assemble only Video Motion / Expression / Camera Movement / Physics clauses."""
    clauses = [extract_clause(values.get(k, "")) for k, _, _, _ in MOTION_FIELDS]
    clauses = [c for c in clauses if c]
    if (extra_notes or "").strip():
        clauses.append(extra_notes.strip())
    return ", ".join(clauses)


_STOPWORDS = {
    "the", "and", "with", "for", "from", "into", "over", "very", "soft", "warm",
    "light", "natural", "looking", "style", "shot", "pose", "hair", "eyes", "skin",
    "body", "face", "camera", "background", "scene", "adult", "modern", "clean",
}


def ascertain_fields_from_prompt(prompt_text: str) -> dict[str, str]:
    """Match a free-form prompt to the closest dropdown option in each Builder field."""
    low = (prompt_text or "").lower()
    p_tokens = set(re.findall(r"[a-z0-9_]+", low))
    matched: dict[str, str] = {}

    for key, _, _, opts in ALL_FIELDS:
        best_opt, best_score = opts[0], 0.0
        for opt in opts[1:]:
            label, clause = opt.split(":", 1) if ":" in opt else (opt, opt)
            l_tokens = [t for t in re.findall(r"[a-z0-9_]+", label.lower()) if len(t) >= 3 and t not in _STOPWORDS]
            c_tokens = [t for t in re.findall(r"[a-z0-9_]+", clause.lower()) if len(t) >= 3 and t not in _STOPWORDS]
            score = 0.0
            for t in l_tokens:
                if t in p_tokens or t in low:
                    score += 2.2
            for t in set(c_tokens):
                if t in p_tokens:
                    score += 1.5
            for phrase in re.split(r"[,/()]+", clause.lower()):
                ph = phrase.strip()
                if len(ph) >= 8 and ph in low:
                    score += 3.0
            norm = score / max(1.0, len(set(c_tokens)) ** 0.35)
            if score >= 1.5 and norm > best_score:
                best_score = norm
                best_opt = opt
        matched[key] = best_opt
    return matched
