<?php
/**
 * Plugin Name:       FOSSLab Tutorial
 * Plugin URI:        https://memristors.uib.es/index.php/education/fosslab/
 * Description:       The analog design flow with free tools and the IHP SG13G2 open PDK: an op-amp from schematic to post-layout simulation. Insert with [fosslab_tutorial] (all chapters, with navigation) or [fosslab_chapter slug="..."].
 * Version:           0.1.0
 * Requires at least: 5.8
 * Requires PHP:      7.4
 * Author:            R. Picos (Universitat de les Illes Balears)
 * License:           Apache-2.0
 * Text Domain:       fosslab-tutorial
 */

if ( ! defined( 'ABSPATH' ) ) {
	exit;
}

define( 'FOSSLAB_TUT_VERSION', '0.1.0' );
define( 'FOSSLAB_TUT_DIR', plugin_dir_path( __FILE__ ) );
define( 'FOSSLAB_TUT_URL', plugin_dir_url( __FILE__ ) );

/** Chapters, in order, from content/chapters.json. */
function fosslab_tut_chapters() {
	static $chapters = null;
	if ( null === $chapters ) {
		$json     = file_get_contents( FOSSLAB_TUT_DIR . 'content/chapters.json' );
		$data     = json_decode( $json, true );
		$chapters = is_array( $data ) ? $data : array();
	}
	return $chapters;
}

function fosslab_tut_find( $slug ) {
	foreach ( fosslab_tut_chapters() as $i => $c ) {
		if ( $c['slug'] === $slug ) {
			return array( $i, $c );
		}
	}
	return array( -1, null );
}

/** Settings used inside the chapters as {{name}}. */
function fosslab_tut_vars() {
	$o = get_option( 'fosslab_tut_options', array() );
	return array(
		'server'  => isset( $o['server'] ) && $o['server'] ? $o['server'] : 'eda.example.edu',
		'prefix'  => isset( $o['prefix'] ) && $o['prefix'] ? $o['prefix'] : '/opt/fosslab',
		'course'  => isset( $o['course'] ) && $o['course'] ? $o['course'] : 'Microelectronics',
		'contact' => isset( $o['contact'] ) ? $o['contact'] : '',
	);
}

function fosslab_tut_render_chapter_body( $chapter ) {
	$file = FOSSLAB_TUT_DIR . 'content/' . basename( $chapter['file'] );
	if ( ! is_readable( $file ) ) {
		return '<p>' . esc_html__( 'Chapter not found.', 'fosslab-tutorial' ) . '</p>';
	}
	$html = file_get_contents( $file );
	foreach ( fosslab_tut_vars() as $k => $v ) {
		$html = str_replace( '{{' . $k . '}}', esc_html( $v ), $html );
	}
	$html = str_replace( '{{img}}', esc_url( FOSSLAB_TUT_URL . 'content/img' ), $html );
	return wp_kses_post( $html );
}

function fosslab_tut_enqueue() {
	wp_enqueue_style( 'fosslab-tutorial', FOSSLAB_TUT_URL . 'assets/fosslab.css', array(), FOSSLAB_TUT_VERSION );
	wp_enqueue_script( 'fosslab-tutorial', FOSSLAB_TUT_URL . 'assets/fosslab.js', array(), FOSSLAB_TUT_VERSION, true );
	wp_localize_script(
		'fosslab-tutorial',
		'fosslabTut',
		array(
			'copy'   => __( 'Copy', 'fosslab-tutorial' ),
			'copied' => __( 'Copied', 'fosslab-tutorial' ),
		)
	);
}

/** Link to a chapter on the current page (?fl=slug). */
function fosslab_tut_link( $slug ) {
	return esc_url( add_query_arg( 'fl', $slug, get_permalink() ) . '#fosslab' );
}

/**
 * [fosslab_tutorial start="overview"]
 * The whole tutorial on one page: chapter list, the selected chapter, and
 * previous/next links. The chapter is chosen with ?fl=<slug>.
 */
function fosslab_tut_shortcode( $atts ) {
	$atts     = shortcode_atts( array( 'start' => '' ), $atts, 'fosslab_tutorial' );
	$chapters = fosslab_tut_chapters();
	if ( ! $chapters ) {
		return '';
	}
	fosslab_tut_enqueue();
	$slug = isset( $_GET['fl'] ) ? sanitize_key( wp_unslash( $_GET['fl'] ) ) : sanitize_key( $atts['start'] ); // phpcs:ignore WordPress.Security.NonceVerification
	list( $idx, $cur ) = fosslab_tut_find( $slug );
	if ( ! $cur ) {
		$idx = 0;
		$cur = $chapters[0];
	}

	$out  = '<div id="fosslab" class="fosslab">';
	$out .= '<nav class="fosslab-toc" aria-label="' . esc_attr__( 'Tutorial chapters', 'fosslab-tutorial' ) . '"><ol>';
	foreach ( $chapters as $i => $c ) {
		$cls  = $i === $idx ? ' class="current"' : '';
		$tag  = ! empty( $c['draft'] ) ? ' <span class="fosslab-badge">' . esc_html__( 'in preparation', 'fosslab-tutorial' ) . '</span>' : '';
		$out .= '<li' . $cls . '><a href="' . fosslab_tut_link( $c['slug'] ) . '">' . esc_html( $c['title'] ) . '</a>' . $tag . '</li>';
	}
	$out .= '</ol></nav>';

	$out .= '<article class="fosslab-chapter">';
	$out .= '<p class="fosslab-kicker">' . esc_html( sprintf( __( 'Chapter %1$d of %2$d', 'fosslab-tutorial' ), $idx + 1, count( $chapters ) ) );
	if ( ! empty( $cur['minutes'] ) ) {
		$out .= ' · ' . esc_html( sprintf( __( 'about %d min', 'fosslab-tutorial' ), $cur['minutes'] ) );
	}
	$out .= '</p><h2 class="fosslab-title">' . esc_html( $cur['title'] ) . '</h2>';
	if ( ! empty( $cur['draft'] ) ) {
		$out .= '<p class="fosslab-draft">' . esc_html__( 'This chapter is in preparation: the outline is final, the worked example with real IHP SG13G2 results is being added.', 'fosslab-tutorial' ) . '</p>';
	}
	$out .= fosslab_tut_render_chapter_body( $cur );

	$out .= '<nav class="fosslab-pager">';
	if ( $idx > 0 ) {
		$p    = $chapters[ $idx - 1 ];
		$out .= '<a class="prev" href="' . fosslab_tut_link( $p['slug'] ) . '">← ' . esc_html( $p['title'] ) . '</a>';
	}
	if ( $idx < count( $chapters ) - 1 ) {
		$n    = $chapters[ $idx + 1 ];
		$out .= '<a class="next" href="' . fosslab_tut_link( $n['slug'] ) . '">' . esc_html( $n['title'] ) . ' →</a>';
	}
	$out .= '</nav></article></div>';
	return $out;
}
add_shortcode( 'fosslab_tutorial', 'fosslab_tut_shortcode' );

/** [fosslab_chapter slug="getting-started"]: one chapter, without navigation. */
function fosslab_tut_chapter_shortcode( $atts ) {
	$atts = shortcode_atts( array( 'slug' => '' ), $atts, 'fosslab_chapter' );
	list( , $c ) = fosslab_tut_find( sanitize_key( $atts['slug'] ) );
	if ( ! $c ) {
		return '';
	}
	fosslab_tut_enqueue();
	return '<div class="fosslab"><article class="fosslab-chapter">' . fosslab_tut_render_chapter_body( $c ) . '</article></div>';
}
add_shortcode( 'fosslab_chapter', 'fosslab_tut_chapter_shortcode' );

/* --- Settings > FOSSLab Tutorial -------------------------------------------- */

function fosslab_tut_admin_menu() {
	add_options_page( 'FOSSLab Tutorial', 'FOSSLab Tutorial', 'manage_options', 'fosslab-tutorial', 'fosslab_tut_settings_page' );
}
add_action( 'admin_menu', 'fosslab_tut_admin_menu' );

function fosslab_tut_register_settings() {
	register_setting(
		'fosslab_tut',
		'fosslab_tut_options',
		array(
			'type'              => 'array',
			'sanitize_callback' => 'fosslab_tut_sanitize',
			'default'           => array(),
		)
	);
}
add_action( 'admin_init', 'fosslab_tut_register_settings' );

function fosslab_tut_sanitize( $in ) {
	$out = array();
	foreach ( array( 'server', 'prefix', 'course', 'contact' ) as $k ) {
		$out[ $k ] = isset( $in[ $k ] ) ? sanitize_text_field( $in[ $k ] ) : '';
	}
	return $out;
}

function fosslab_tut_settings_page() {
	if ( ! current_user_can( 'manage_options' ) ) {
		return;
	}
	$v      = fosslab_tut_vars();
	$fields = array(
		'server'  => __( 'Server students log into (host name)', 'fosslab-tutorial' ),
		'prefix'  => __( 'FOSSLab install folder on the server', 'fosslab-tutorial' ),
		'course'  => __( 'Course name', 'fosslab-tutorial' ),
		'contact' => __( 'Contact for problems (shown in Getting started)', 'fosslab-tutorial' ),
	);
	echo '<div class="wrap"><h1>FOSSLab Tutorial</h1>';
	echo '<p>' . esc_html__( 'Insert the tutorial in any page with the shortcode', 'fosslab-tutorial' ) . ' <code>[fosslab_tutorial]</code>. ';
	echo esc_html__( 'One chapter alone:', 'fosslab-tutorial' ) . ' <code>[fosslab_chapter slug="getting-started"]</code>.</p>';
	echo '<form method="post" action="options.php">';
	settings_fields( 'fosslab_tut' );
	echo '<table class="form-table">';
	foreach ( $fields as $k => $label ) {
		echo '<tr><th scope="row"><label for="fl_' . esc_attr( $k ) . '">' . esc_html( $label ) . '</label></th>';
		echo '<td><input class="regular-text" id="fl_' . esc_attr( $k ) . '" name="fosslab_tut_options[' . esc_attr( $k ) . ']" value="' . esc_attr( $v[ $k ] ) . '"></td></tr>';
	}
	echo '</table>';
	submit_button();
	echo '</form><h2>' . esc_html__( 'Chapters', 'fosslab-tutorial' ) . '</h2><ol>';
	foreach ( fosslab_tut_chapters() as $c ) {
		echo '<li><code>' . esc_html( $c['slug'] ) . '</code> ' . esc_html( $c['title'] ) . ( ! empty( $c['draft'] ) ? ' <em>(' . esc_html__( 'in preparation', 'fosslab-tutorial' ) . ')</em>' : '' ) . '</li>';
	}
	echo '</ol></div>';
}
