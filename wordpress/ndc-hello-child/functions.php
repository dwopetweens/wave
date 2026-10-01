<?php
/**
 * NDC Hello Child: site-wide Elementor header/footer and the NDC logo.
 *
 * The header and footer are ordinary Elementor templates (Templates > Saved
 * Templates), so they are edited once in the visual editor and appear on every
 * page. This gives free Elementor the part of Elementor Pro's Theme Builder
 * that this site needs. If Elementor Pro is ever installed, its Theme Builder
 * header/footer take priority automatically.
 *
 * @package NDC_Hello_Child
 */

defined( 'ABSPATH' ) || exit;

define( 'NDC_CHILD_VERSION', '1.1.0' );

/** Template titles looked up when nothing is chosen in the Customizer. */
const NDC_PART_TITLES = array(
	'header' => 'NDC Site Header',
	'footer' => 'NDC Site Footer',
);

add_action(
	'wp_enqueue_scripts',
	static function () {
		wp_enqueue_style( 'ndc-hello-child', get_stylesheet_uri(), array(), NDC_CHILD_VERSION );
	},
	20
);

/* -------------------------------------------------------------------------
 * Logo shortcode: [ndc_logo variant="light|dark" height="56" height_mobile="40" link="yes"]
 * "light" is the cream logo for dark backgrounds; "dark" is the black logo.
 * ---------------------------------------------------------------------- */
add_shortcode(
	'ndc_logo',
	static function ( $atts ) {
		$a = shortcode_atts(
			array(
				'variant'       => 'light',
				'height'        => '56',
				'height_mobile' => '',
				'link'          => 'yes',
			),
			$atts,
			'ndc_logo'
		);

		$variant = 'dark' === $a['variant'] ? 'dark' : 'light';
		$height  = max( 16, min( 400, (int) $a['height'] ) );
		$mobile  = $a['height_mobile'] ? max( 16, min( 400, (int) $a['height_mobile'] ) ) : 0;
		$style   = '--ndc-logo-h:' . $height . 'px;' . ( $mobile ? '--ndc-logo-h-mobile:' . $mobile . 'px;' : '' );
		$name    = get_bloginfo( 'name' ) ? get_bloginfo( 'name' ) : 'NDC Consulting Group';

		// Source artwork is 894 x 371; width/height attributes prevent layout shift.
		$img = sprintf(
			'<img class="ndc-logo" src="%1$s" width="%2$d" height="%3$d" alt="%4$s" style="%5$s" decoding="async">',
			esc_url( get_stylesheet_directory_uri() . '/assets/img/ndc-logo-' . $variant . '.png' ),
			(int) round( $height * 894 / 371 ),
			$height,
			esc_attr( $name ),
			esc_attr( $style )
		);

		if ( 'no' === $a['link'] ) {
			return $img;
		}
		return '<a class="ndc-logo-link" href="' . esc_url( home_url( '/' ) ) . '" rel="home">' . $img . '</a>';
	}
);

/* -------------------------------------------------------------------------
 * Site header / footer from Elementor templates
 * ---------------------------------------------------------------------- */

/**
 * Find the Elementor template to use for a site part.
 *
 * @param string $part 'header' or 'footer'.
 * @return int Template post ID, or 0.
 */
function ndc_part_template_id( $part ) {
	$chosen = (int) get_theme_mod( "ndc_{$part}_template", 0 );
	if ( $chosen && 'publish' === get_post_status( $chosen ) ) {
		return $chosen;
	}
	$found = get_posts(
		array(
			'post_type'      => 'elementor_library',
			'post_status'    => 'publish',
			'title'          => NDC_PART_TITLES[ $part ],
			'posts_per_page' => 1,
			'orderby'        => 'ID',
			'order'          => 'DESC',
			'fields'         => 'ids',
			'no_found_rows'  => true,
		)
	);
	if ( $found ) {
		return (int) $found[0];
	}
	// Tolerate renamed copies such as "NDC Site Header (1)" or different case.
	foreach ( get_posts(
		array(
			'post_type'      => 'elementor_library',
			'post_status'    => 'publish',
			's'              => NDC_PART_TITLES[ $part ],
			'posts_per_page' => 10,
			'orderby'        => 'ID',
			'order'          => 'DESC',
		)
	) as $tpl ) {
		if ( 0 === stripos( trim( $tpl->post_title ), NDC_PART_TITLES[ $part ] ) ) {
			return (int) $tpl->ID;
		}
	}
	return 0;
}

/**
 * Print a site part. Returns false if no template is available, so the
 * caller can fall back to Hello's default header/footer.
 *
 * @param string $part 'header' or 'footer'.
 * @return bool
 */
function ndc_render_part( $part ) {
	if ( ! did_action( 'elementor/loaded' ) || ! class_exists( '\Elementor\Plugin' ) ) {
		return false;
	}
	$id = ndc_part_template_id( $part );
	if ( ! $id ) {
		return false;
	}
	$html = \Elementor\Plugin::instance()->frontend->get_builder_content_for_display( $id, true );
	if ( '' === trim( (string) $html ) ) {
		return false;
	}
	$tag = 'header' === $part ? 'header' : 'footer';
	printf( '<%1$s id="site-%1$s" class="ndc-site-%1$s">%2$s</%1$s>', $tag, $html ); // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped -- Elementor output.
	return true;
}

/* -------------------------------------------------------------------------
 * Customizer: Appearance > Customize > NDC Header & Footer
 * ---------------------------------------------------------------------- */
add_action(
	'customize_register',
	static function ( WP_Customize_Manager $wp_customize ) {
		$choices = array( 0 => __( '— Automatic (by template name) —', 'ndc-hello-child' ) );
		foreach ( get_posts(
			array(
				'post_type'      => 'elementor_library',
				'post_status'    => 'publish',
				'posts_per_page' => 200,
				'orderby'        => 'title',
				'order'          => 'ASC',
			)
		) as $tpl ) {
			$choices[ $tpl->ID ] = $tpl->post_title;
		}

		$wp_customize->add_section(
			'ndc_parts',
			array(
				'title'       => __( 'NDC Header & Footer', 'ndc-hello-child' ),
				'description' => sprintf(
					/* translators: 1: header template title, 2: footer template title. */
					__( 'Choose which Elementor templates appear at the top and bottom of every page. "Automatic" uses the templates named "%1$s" and "%2$s".', 'ndc-hello-child' ),
					NDC_PART_TITLES['header'],
					NDC_PART_TITLES['footer']
				),
				'priority'    => 30,
			)
		);
		foreach ( array( 'header', 'footer' ) as $part ) {
			$wp_customize->add_setting(
				"ndc_{$part}_template",
				array(
					'default'           => 0,
					'sanitize_callback' => 'absint',
				)
			);
			$wp_customize->add_control(
				"ndc_{$part}_template",
				array(
					'section' => 'ndc_parts',
					'label'   => 'header' === $part ? __( 'Header template', 'ndc-hello-child' ) : __( 'Footer template', 'ndc-hello-child' ),
					'type'    => 'select',
					'choices' => $choices,
				)
			);
		}
	}
);

/* -------------------------------------------------------------------------
 * Built-in header/footer: used only if the Elementor templates can't be
 * found or rendered, so the logo and navigation always appear.
 * ---------------------------------------------------------------------- */
function ndc_builtin_part( $part ) {
	$logo = do_shortcode( 'header' === $part ? '[ndc_logo height="64" height_mobile="46"]' : '[ndc_logo height="96" height_mobile="72"]' );
	$links = array(
		__( 'About', 'ndc-hello-child' )    => home_url( '/#about' ),
		__( 'Services', 'ndc-hello-child' ) => home_url( '/#services' ),
		__( 'Process', 'ndc-hello-child' )  => home_url( '/#process' ),
	);
	$nav = '';
	foreach ( $links as $label => $url ) {
		$nav .= '<a href="' . esc_url( $url ) . '">' . esc_html( $label ) . '</a>';
	}
	if ( 'header' === $part ) {
		echo '<header id="site-header" class="ndc-builtin ndc-builtin--header"><div class="ndc-builtin__inner">' . $logo // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped
			. '<nav class="ndc-builtin__nav" aria-label="' . esc_attr__( 'Main', 'ndc-hello-child' ) . '">' . $nav // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped
			. '<a class="ndc-builtin__cta" href="' . esc_url( home_url( '/contact/' ) ) . '">' . esc_html__( 'Contact Us', 'ndc-hello-child' ) . '</a></nav></div></header>';
		return;
	}
	$nav .= '<a href="' . esc_url( home_url( '/contact/' ) ) . '">' . esc_html__( 'Contact', 'ndc-hello-child' ) . '</a>';
	echo '<footer id="site-footer" class="ndc-builtin ndc-builtin--footer"><div class="ndc-builtin__inner">' . $logo // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped
		. '<nav class="ndc-builtin__nav" aria-label="' . esc_attr__( 'Footer', 'ndc-hello-child' ) . '">' . $nav . '</nav></div>' // phpcs:ignore WordPress.Security.EscapeOutput.OutputNotEscaped
		. '<div class="ndc-builtin__legal"><span>&copy; ' . esc_html( wp_date( 'Y' ) ) . ' NDC Consulting Group. All rights reserved.</span><span>Built for better business.</span></div></footer>';
}

/* -------------------------------------------------------------------------
 * Auto-import: bring in the bundled header/footer templates if missing.
 * ---------------------------------------------------------------------- */
function ndc_import_missing_parts( $force = false ) {
	if ( ! did_action( 'elementor/loaded' ) || ! class_exists( '\Elementor\Plugin' ) || ! current_user_can( 'manage_options' ) ) {
		return array();
	}
	$source = \Elementor\Plugin::$instance->templates_manager->get_source( 'local' );
	if ( ! $source ) {
		return array();
	}
	$done = array();
	foreach ( array( 'header', 'footer' ) as $part ) {
		if ( ! $force && ndc_part_template_id( $part ) ) {
			continue;
		}
		$file = get_stylesheet_directory() . "/templates/ndc-{$part}.json";
		if ( ! is_readable( $file ) ) {
			continue;
		}
		$result = $source->import_template( basename( $file ), $file );
		if ( ! is_wp_error( $result ) && ! empty( $result[0]['template_id'] ) ) {
			$done[ $part ] = (int) $result[0]['template_id'];
			set_theme_mod( "ndc_{$part}_template", $done[ $part ] );
		}
	}
	return $done;
}

add_action(
	'admin_init',
	static function () {
		if ( wp_doing_ajax() || get_option( 'ndc_parts_imported' ) === NDC_CHILD_VERSION ) {
			return;
		}
		if ( did_action( 'elementor/loaded' ) && current_user_can( 'manage_options' ) ) {
			ndc_import_missing_parts();
			update_option( 'ndc_parts_imported', NDC_CHILD_VERSION, false );
		}
	}
);

/* -------------------------------------------------------------------------
 * Appearance > NDC Site Status: shows what is working, with a repair button.
 * ---------------------------------------------------------------------- */
add_action(
	'admin_menu',
	static function () {
		add_theme_page( __( 'NDC Site Status', 'ndc-hello-child' ), __( 'NDC Site Status', 'ndc-hello-child' ), 'manage_options', 'ndc-site-status', 'ndc_status_page' );
	}
);

function ndc_status_page() {
	$notice = '';
	if ( isset( $_POST['ndc_repair'] ) && check_admin_referer( 'ndc_repair' ) ) {
		$done   = ndc_import_missing_parts( true );
		$notice = $done ? __( 'Header and footer re-imported and selected.', 'ndc-hello-child' ) : __( 'Nothing was imported. Is Elementor active?', 'ndc-hello-child' );
		if ( class_exists( '\Elementor\Plugin' ) ) {
			\Elementor\Plugin::$instance->files_manager->clear_cache();
		}
	}
	$parent = wp_get_theme( 'hello-elementor' );
	$rows   = array(
		__( 'Active theme', 'ndc-hello-child' )      => array( 'ndc-hello-child' === get_stylesheet(), wp_get_theme()->get( 'Name' ) . ' ' . wp_get_theme()->get( 'Version' ) ),
		__( 'Hello Elementor (parent)', 'ndc-hello-child' ) => array( $parent->exists(), $parent->exists() ? $parent->get( 'Version' ) : __( 'not installed', 'ndc-hello-child' ) ),
		__( 'Elementor plugin', 'ndc-hello-child' )  => array( defined( 'ELEMENTOR_VERSION' ), defined( 'ELEMENTOR_VERSION' ) ? ELEMENTOR_VERSION : __( 'not active', 'ndc-hello-child' ) ),
		__( 'Elementor Pro', 'ndc-hello-child' )     => array( true, defined( 'ELEMENTOR_PRO_VERSION' ) ? ELEMENTOR_PRO_VERSION . ' — ' . __( 'its Theme Builder header/footer, if any, take priority', 'ndc-hello-child' ) : __( 'not installed (fine)', 'ndc-hello-child' ) ),
	);
	foreach ( array( 'header', 'footer' ) as $part ) {
		$id = ndc_part_template_id( $part );
		$rows[ 'header' === $part ? __( 'Header template', 'ndc-hello-child' ) : __( 'Footer template', 'ndc-hello-child' ) ] = array( (bool) $id, $id ? get_the_title( $id ) . " (#{$id})" : __( 'not found — the built-in header/footer is shown instead', 'ndc-hello-child' ) );
	}
	$logo = get_stylesheet_directory() . '/assets/img/ndc-logo-light.png';
	$rows[ __( 'Logo files', 'ndc-hello-child' ) ] = array( is_readable( $logo ), is_readable( $logo ) ? __( 'present', 'ndc-hello-child' ) : __( 'missing', 'ndc-hello-child' ) );
	?>
	<div class="wrap">
		<h1><?php esc_html_e( 'NDC Site Status', 'ndc-hello-child' ); ?></h1>
		<?php if ( $notice ) : ?><div class="notice notice-success"><p><?php echo esc_html( $notice ); ?></p></div><?php endif; ?>
		<table class="widefat striped" style="max-width:820px">
			<tbody>
			<?php foreach ( $rows as $label => $row ) : ?>
				<tr><td style="width:240px"><strong><?php echo esc_html( $label ); ?></strong></td>
					<td><?php echo $row[0] ? '&#9989; ' : '&#10060; '; ?><?php echo esc_html( $row[1] ); ?></td></tr>
			<?php endforeach; ?>
			</tbody>
		</table>
		<form method="post" style="margin-top:20px">
			<?php wp_nonce_field( 'ndc_repair' ); ?>
			<p><?php esc_html_e( 'Re-import the NDC header and footer from the theme, select them, and clear Elementor\'s cache:', 'ndc-hello-child' ); ?></p>
			<?php submit_button( __( 'Repair header & footer', 'ndc-hello-child' ), 'primary', 'ndc_repair', false ); ?>
		</form>
	</div>
	<?php
}
