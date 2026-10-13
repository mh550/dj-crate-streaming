from scripts import folders_to_playlists as f2p


def test_strips_trailing_album_and_artist_dirs():
    assert f2p.playlist_name("Tea tent/Donald Byrd/Fancy Free", album="Fancy Free", artists=["Donald Byrd"]) == "Tea tent"
    assert f2p.playlist_name("playlists/jazz bar/Joe Henderson/Page One", album="Page One", artists=["Joe Henderson"]) == "playlists / jazz bar"


def test_keeps_curation_subfolders():
    assert f2p.playlist_name("Haus-Jungle-GhettoTech-Dance/DnB", album="Some Album", artists=["X"]) == "Haus-Jungle-GhettoTech-Dance / DnB"
    assert f2p.playlist_name("Soul-Motown/studio-pop-70s-80s-90s/Stevie Wonder", album="Innervisions", artists=["Stevie Wonder"]) == "Soul-Motown / studio-pop-70s-80s-90s"


def test_matching_is_forgiving_and_handles_placeholders():
    assert f2p.playlist_name("playlists/Music Center/Unknown Artist/Aseda", album="Aseda (Deluxe)", artists=["Kwabs"]) == "playlists / Music Center"
    assert f2p.playlist_name("Tea tent/masayoshi takanaka/オン・ギター", album="オン・ギター", artists=["Masayoshi Takanaka"]) == "Tea tent"


def test_root_files_have_no_playlist():
    assert f2p.playlist_name("", album="A", artists=["B"]) is None


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


def test_unknown_album_placeholder_never_matches_a_folder():
    assert f2p.playlist_name("sockseek/Tea tent", album="[Unknown Album]", artists=["Admas"]) == "sockseek / Tea tent"
    assert f2p.playlist_name("sockseek/secondset", album="", artists=["[Unknown Artist]"]) == "sockseek / secondset"


def test_folder_holding_several_albums_is_curation_even_if_named_like_one():
    assert f2p.playlist_name("sockseek/buck-bumble", album="Buck Bumble (Original Soundtrack)", artists=["X"],
                             albums_in=lambda f: 4) == "sockseek / buck-bumble"
    assert f2p.playlist_name("sockseek/clouds", album="Clouds", artists=["X"], albums_in=lambda f: 2) == "sockseek / clouds"


def test_single_album_leaf_under_an_artist_dir_with_no_audio_is_an_album_dir():
    name = f2p.playlist_name("playlists/skate/Three Dog Night/Celebrate_", album="[Unknown Album]", artists=["[Unknown Artist]"],
                             has_audio=lambda f: f != "playlists/skate/Three Dog Night", albums_in=lambda f: 1)
    assert name == "playlists / skate"
    # a one-track curation subfolder directly under its parent is not an album dir
    assert f2p.playlist_name("disco-fonk-daft-punk/funk", album="Some LP", artists=["Someone"],
                             has_audio=lambda f: False, albums_in=lambda f: 1) == "disco-fonk-daft-punk / funk"


def test_cover_art_marks_album_dir_and_parent_artist_dir_without_audio_is_dropped():
    name = f2p.playlist_name("playlists/shakori/Marvin Gaye/Midnight Love_", album="Midnight Love (Deluxe Edition)", artists=["", ""],
                             album_dir=lambda f: f == "playlists/shakori/Marvin Gaye/Midnight Love_",
                             has_audio=lambda f: f != "playlists/shakori/Marvin Gaye")
    assert name == "playlists / shakori"


def test_underscores_from_sanitised_names_do_not_block_matching():
    assert f2p.playlist_name("x/Electric Light Orchestra/All Over The World_ The Very Best Of ELO",
                             album="All Over the World: The Very Best of ELO", artists=["Electric Light Orchestra"]) == "x"


def test_plan_album_dir_detection_needs_a_real_image(tmp_path):
    (tmp_path / "sockseek" / "shakori").mkdir(parents=True)
    (tmp_path / "playlists" / "jazz" / "Artist" / "Album").mkdir(parents=True)
    (tmp_path / "playlists" / "jazz" / "Artist" / "Album" / "cover.jpg").write_bytes(b"x")
    rows = [
        {"original_path": "sockseek/shakori/a.mp3", "folder": "sockseek/shakori", "new_path": "n1"},
        {"original_path": "playlists/jazz/Artist/Album/b.flac", "folder": "playlists/jazz/Artist/Album", "new_path": "n2"},
    ]
    songs = {"n1": {"id": "1", "album": "", "artists": [""]}, "n2": {"id": "2", "album": "Other", "artists": [""]}}
    plan, _ = f2p.plan(rows, songs, source=tmp_path)
    assert plan == {"sockseek / shakori": ["1"], "playlists / jazz": ["2"]}


def test_artist_dir_directly_under_curation_pops_once_even_with_one_album_inside():
    assert f2p.playlist_name("Soul-Motown/studio-pop-70s-80s-90s/Stevie Wonder", album="Songs in the Key of Life",
                             artists=["Stevie Wonder"], has_audio=lambda f: False, albums_in=lambda f: 1) == "Soul-Motown / studio-pop-70s-80s-90s"


def test_tag_contained_in_folder_name_is_not_a_match():
    # a vibe folder that happens to contain an artist's name stays curation
    assert f2p.playlist_name("x/disco-fonk-daft-punk", album="Discovery", artists=["Daft Punk"], albums_in=lambda f: 3) == "x / disco-fonk-daft-punk"


def test_self_titled_album_pops_artist_and_album_dirs():
    assert f2p.playlist_name("playlists/perfect songs/Air/Air", album="Air", artists=["Air"],
                             has_audio=lambda f: False, albums_in=lambda f: 1) == "playlists / perfect songs"
    assert f2p.playlist_name("playlists/Music Center/Unknown Artist/Jaco Pastorius", album="Jaco Pastorius",
                             artists=["Jaco Pastorius"], has_audio=lambda f: False, albums_in=lambda f: 1) == "playlists / Music Center"
