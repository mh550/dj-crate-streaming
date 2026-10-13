from scripts import folders_to_playlists as f2p


def name(folder, album="", artists=(), audio=(), albums=None):
    return f2p.playlist_name(folder, set(albums) if albums is not None else {album}, set(artists), set(audio))


def test_strips_trailing_album_and_artist_dirs():
    assert name("Tea tent/Donald Byrd/Fancy Free", "Fancy Free", ["Donald Byrd"]) == "Tea tent"
    assert name("playlists/jazz bar/Joe Henderson/Page One", "Page One", ["Joe Henderson"]) == "playlists / jazz bar"


def test_keeps_curation_subfolders():
    assert name("Haus-Jungle-GhettoTech-Dance/DnB", "Some Album", ["X"], audio=["Haus-Jungle-GhettoTech-Dance"]) == "Haus-Jungle-GhettoTech-Dance / DnB"
    assert name("Soul-Motown/studio-pop-70s-80s-90s/Stevie Wonder", "Innervisions", ["Stevie Wonder"]) == "Soul-Motown / studio-pop-70s-80s-90s"


def test_matching_is_forgiving_and_handles_placeholders():
    assert name("playlists/Music Center/Unknown Artist/Aseda", "Aseda (Deluxe)", ["Kwabs"]) == "playlists / Music Center"
    assert name("Tea tent/masayoshi takanaka/オン・ギター", "オン・ギター", ["Masayoshi Takanaka"]) == "Tea tent"
    assert name("sockseek/Tea tent", "[Unknown Album]", ["Admas"], audio=["sockseek"]) == "sockseek / Tea tent"
    assert name("sockseek/secondset", "", ["[Unknown Artist]"], audio=["sockseek"]) == "sockseek / secondset"


def test_root_and_top_level_folders():
    assert name("", "A", ["B"]) is None
    assert name("ambient", "A", ["B"]) == "ambient"


def test_folder_holding_several_albums_is_curation_even_if_named_like_one():
    assert name("sockseek/buck-bumble", artists=["X"], albums=["Buck Bumble (Original Soundtrack)", "B", "C", "D"]) == "sockseek / buck-bumble"
    assert name("sockseek/clouds", artists=["X"], albums=["Clouds", "Other"]) == "sockseek / clouds"


def test_artist_album_pair_is_structural_even_with_placeholder_tags():
    assert name("playlists/skate/Three Dog Night/Celebrate_", "[Unknown Album]", ["[Unknown Artist]"]) == "playlists / skate"
    # a one-track curation subfolder directly under its parent is not an album dir
    assert name("disco-fonk-daft-punk/funk", "Some LP", ["Someone"]) == "disco-fonk-daft-punk / funk"


def test_artist_dir_directly_under_curation_pops_once_even_with_one_album_inside():
    assert name("Soul-Motown/studio-pop-70s-80s-90s/Stevie Wonder", "Songs in the Key of Life", ["Stevie Wonder"]) == "Soul-Motown / studio-pop-70s-80s-90s"


def test_self_titled_album_pops_artist_and_album_dirs():
    assert name("playlists/perfect songs/Air/Air", "Air", ["Air"]) == "playlists / perfect songs"
    assert name("playlists/Music Center/Unknown Artist/Jaco Pastorius", "Jaco Pastorius", ["Jaco Pastorius"]) == "playlists / Music Center"


def test_underscores_and_tag_direction():
    assert name("x/Electric Light Orchestra/All Over The World_ The Very Best Of ELO",
                "All Over the World: The Very Best of ELO", ["Electric Light Orchestra"]) == "x"
    # a vibe folder that happens to contain an artist's name stays curation
    assert name("x/disco-fonk-daft-punk", artists=["Daft Punk"], albums=["Discovery", "Homework"]) == "x / disco-fonk-daft-punk"


def test_plan_groups_song_ids_in_original_order_and_dedupes():
    rows = [
        {"original_path": "Tea tent/b.flac", "folder": "Tea tent", "new_path": "B/b.flac"},
        {"original_path": "Tea tent/a.flac", "folder": "Tea tent", "new_path": "A/a.flac"},
        {"original_path": "Tea tent/a2.flac", "folder": "Tea tent", "new_path": "A/a.flac"},   # byte-identical copy
        {"original_path": "root.mp3", "folder": "", "new_path": "R/root.mp3"},
        {"original_path": "x/lost.mp3", "folder": "x", "new_path": ""},                       # unmapped
    ]
    songs = {"B/b.flac": {"id": "2", "album": "", "artists": []}, "A/a.flac": {"id": "1", "album": "", "artists": []},
             "R/root.mp3": {"id": "3", "album": "", "artists": []}}
    plan, skipped = f2p.plan(rows, songs)
    assert plan == {"Tea tent": ["1", "2"]}
    assert skipped == ["root.mp3", "x/lost.mp3"]


def test_plan_classifies_a_folder_from_all_its_tracks():
    rows = [{"original_path": f"sockseek/clouds/{i}.mp3", "folder": "sockseek/clouds", "new_path": f"n{i}"} for i in range(2)]
    songs = {"n0": {"id": "a", "album": "Clouds", "artists": ["X"]}, "n1": {"id": "b", "album": "Other", "artists": ["Y"]}}
    plan, _ = f2p.plan(rows, songs)
    assert plan == {"sockseek / clouds": ["a", "b"]}
